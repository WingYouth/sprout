"""Change proposal lifecycle: request, approve, reject, apply, rollback.

Every transition rule lives here so the Runtime only wires the service up.
Approvals are task-scoped and created with ``single_use=False`` because apply
and rollback share one grant, while no other task may reuse it (Herness spec
11.5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from Sprout.events import EventBus
from Sprout.execution.apply import ApplyBroker
from Sprout.execution.models import (
    ApplyResult,
    ChangeProposal,
    ChangeProposalStatus,
    TestResult,
)
from Sprout.runtime.state import ChangeProposalStateMachine
from Sprout.security.approval import ApprovalManager
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.storage.contracts.operational import OperationalStore
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import Workspace


def blocking_test_failures(
    results: Sequence[TestResult], files_changed: Sequence[str] = ()
) -> list[str]:
    """Verification results that should stop a change from landing.

    ``failed``, not ``not passed``. A command the policy withheld never ran, so
    blocking on it protects nobody: it refuses a change that was never judged,
    after a human has already reviewed the diff and approved it. A real failure
    still blocks, as it should.
    """
    changed_languages: set[str] = set()
    suffix_languages = {
        ".py": {"python"},
        ".js": {"node"},
        ".jsx": {"node"},
        ".mjs": {"node"},
        ".cjs": {"node"},
        ".ts": {"node", "typescript"},
        ".tsx": {"node", "typescript"},
        ".go": {"go"},
        ".java": {"java"},
        ".kt": {"kotlin"},
        ".kts": {"kotlin"},
        ".c": {"c-cpp"},
        ".h": {"c-cpp"},
        ".cc": {"c-cpp"},
        ".cpp": {"c-cpp"},
        ".cxx": {"c-cpp"},
        ".hpp": {"c-cpp"},
    }
    manifest_languages = {
        "pyproject.toml": {"python"},
        "requirements.txt": {"python"},
        "package.json": {"node"},
        "package-lock.json": {"node"},
        "pnpm-lock.yaml": {"node"},
        "yarn.lock": {"node"},
        "go.mod": {"go"},
        "pom.xml": {"java"},
        "build.gradle": {"java"},
        "build.gradle.kts": {"kotlin"},
        "settings.gradle": {"java"},
        "settings.gradle.kts": {"kotlin"},
        "cmakelists.txt": {"c-cpp"},
        "makefile": {"c-cpp"},
        "meson.build": {"c-cpp"},
    }
    for raw_path in files_changed:
        path = Path(str(raw_path).replace("\\", "/"))
        changed_languages.update(suffix_languages.get(path.suffix.casefold(), set()))
        changed_languages.update(manifest_languages.get(path.name.casefold(), set()))

    command_languages = {
        "pytest": {"python"},
        "python": {"python"},
        "python3": {"python"},
        "ruff": {"python"},
        "mypy": {"python"},
        "node": {"node", "typescript"},
        "npm": {"node", "typescript"},
        "pnpm": {"node", "typescript"},
        "yarn": {"node", "typescript"},
        "tsc": {"node", "typescript"},
        "go": {"go"},
        "mvn": {"java"},
        "gradle": {"java", "kotlin"},
        "gradlew": {"java", "kotlin"},
        "cmake": {"c-cpp"},
        "make": {"c-cpp"},
        "cc": {"c-cpp"},
        "gcc": {"c-cpp"},
        "c++": {"c-cpp"},
        "g++": {"c-cpp"},
        "clang": {"c-cpp"},
        "clang++": {"c-cpp"},
    }

    failures = []
    for item in results:
        if not item.failed:
            continue
        command = str(getattr(item, "name", "")).partition(": ")[2].split()
        languages = command_languages.get(command[0], set()) if command else set()
        if changed_languages and languages and not (languages & changed_languages):
            continue
        failures.append(str(getattr(item, "name", "verification")))
    return failures


class ChangeProposalService:
    """Owns the change proposal state machine for one runtime."""

    def __init__(
        self,
        metadata: MetadataStore,
        operational: OperationalStore,
        apply_broker: ApplyBroker,
        *,
        events: EventBus | None = None,
        approvals: ApprovalManager | None = None,
    ) -> None:
        self._metadata = metadata
        self._apply_broker = apply_broker
        self._approvals = approvals or ApprovalManager(operational, events=events)

    async def get(self, proposal_id: str) -> ChangeProposal | None:
        return await self._metadata.get_change_proposal(proposal_id)

    async def list_for_task(self, task_id: str) -> list[ChangeProposal]:
        return await self._metadata.list_change_proposals(task_id)

    async def find(self, prefix: str) -> ChangeProposal | None:
        """Resolve a proposal by id prefix across every task."""
        for task in await self._metadata.list_tasks():
            for proposal in await self._metadata.list_change_proposals(task.id):
                if proposal.id.startswith(prefix):
                    return proposal
        return None

    async def request_approval(self, proposal_id: str) -> ChangeProposal:
        proposal = await self._require(proposal_id)
        if proposal.status not in {
            ChangeProposalStatus.PENDING,
            ChangeProposalStatus.REJECTED,
        }:
            raise ValueError(
                f"Proposal {proposal.id} cannot be requested from {proposal.status.value}"
            )
        ChangeProposalStateMachine.validate(
            proposal.status,
            ChangeProposalStatus.PENDING,
        )
        return await self._save(replace(proposal, status=ChangeProposalStatus.PENDING))

    async def approve(
        self,
        proposal_id: str,
        *,
        decided_by: str = "cli",
        allow_failing_tests: bool = False,
    ) -> ChangeProposal:
        proposal = await self._require(proposal_id)
        if proposal.status is not ChangeProposalStatus.PENDING:
            raise ValueError(
                f"Proposal {proposal.id} cannot be approved from {proposal.status.value}"
            )
        ChangeProposalStateMachine.validate(
            proposal.status,
            ChangeProposalStatus.APPROVED,
        )
        record = await self._approvals.request(
            "git.commit",
            {"proposal_id": proposal.id, "risk": proposal.risk},
            task_id=proposal.task_id,
            single_use=False,
            resource_scope=proposal.id,
            source="interactive",
            session_id=await self._task_session_id(proposal.task_id),
        )
        await self._approvals.decide(record.id, approved=True, decided_by=decided_by)
        metadata = dict(proposal.metadata)
        if allow_failing_tests:
            metadata["allow_failing_tests_approved"] = True
        return await self._save(
            replace(
                proposal,
                status=ChangeProposalStatus.APPROVED,
                metadata=metadata,
            )
        )

    async def _task_session_id(self, task_id: str) -> str:
        task = await self._metadata.get_task(task_id)
        if task is None:
            return ""
        return str(task.metadata.get("session_id") or "")

    async def reject(self, proposal_id: str, *, reason: str = "") -> ChangeProposal:
        proposal = await self._require(proposal_id)
        if proposal.status is not ChangeProposalStatus.PENDING:
            raise ValueError(
                f"Proposal {proposal.id} cannot be rejected from {proposal.status.value}"
            )
        ChangeProposalStateMachine.validate(
            proposal.status,
            ChangeProposalStatus.REJECTED,
        )
        return await self._save(
            replace(
                proposal,
                status=ChangeProposalStatus.REJECTED,
                metadata={**proposal.metadata, "rejection_reason": reason},
            )
        )

    async def apply(
        self, proposal_id: str, *, allow_failing_tests: bool = False
    ) -> ApplyResult:
        proposal = await self._require(proposal_id)
        if proposal.status is not ChangeProposalStatus.APPROVED:
            raise ValueError(
                f"Proposal {proposal.id} must be approved before apply, "
                f"current={proposal.status.value}"
            )
        failing = blocking_test_failures(
            proposal.test_results, proposal.files_changed
        )
        if failing and not allow_failing_tests:
            # Approving a change used to be enough to land it even when the
            # verification the task itself ran had failed. The failure is now
            # reported instead of being discovered after the fact.
            return ApplyResult(
                proposal_id=proposal.id,
                applied=False,
                reason=(
                    "Verification failed for "
                    + ", ".join(failing)
                    + "; re-apply with allow_failing_tests to land it anyway"
                ),
            )
        ChangeProposalStateMachine.validate(
            proposal.status,
            ChangeProposalStatus.APPLIED,
        )
        workspace = await self._task_workspace(proposal.task_id)
        result = await self._apply_broker.apply(
            proposal,
            workspace,
            scope=await self._task_scope(proposal.task_id),
            session_id=await self._task_session_id(proposal.task_id),
        )
        if result.applied:
            metadata = dict(proposal.metadata)
            if result.base_commit:
                metadata["base_commit"] = result.base_commit
            if result.applied_commit:
                metadata["applied_commit"] = result.applied_commit
            await self._save(
                replace(
                    proposal,
                    status=ChangeProposalStatus.APPLIED,
                    metadata=metadata,
                )
            )
        return result

    async def rollback(self, proposal_id: str) -> ApplyResult:
        proposal = await self._require(proposal_id)
        if proposal.status is not ChangeProposalStatus.APPLIED:
            raise ValueError(
                f"Proposal {proposal.id} must be applied before rollback, "
                f"current={proposal.status.value}"
            )
        ChangeProposalStateMachine.validate(
            proposal.status,
            ChangeProposalStatus.ROLLED_BACK,
        )
        workspace = await self._task_workspace(proposal.task_id)
        result = await self._apply_broker.rollback(
            proposal,
            workspace,
            scope=await self._task_scope(proposal.task_id),
            session_id=await self._task_session_id(proposal.task_id),
        )
        if result.applied:
            await self._save(replace(proposal, status=ChangeProposalStatus.ROLLED_BACK))
        return result

    async def _require(self, proposal_id: str) -> ChangeProposal:
        proposal = await self._metadata.get_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Change proposal not found: {proposal_id}")
        return proposal

    async def _task_workspace(self, task_id: str) -> Workspace:
        task = await self._metadata.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        workspace = await self._metadata.get_workspace(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")
        return workspace

    async def _task_scope(self, task_id: str) -> DelegationScope:
        """The scope the task was created with; apply must not exceed it."""
        task = await self._metadata.get_task(task_id)
        return task.delegation_scope if task is not None else DelegationScope()

    async def _save(self, proposal: ChangeProposal) -> ChangeProposal:
        await self._metadata.save_change_proposal(proposal)
        return proposal

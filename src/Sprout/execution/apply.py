"""Apply boundary for change proposals."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.execution.git_env import git_args, git_env
from Sprout.execution.models import ApplyResult, ChangeProposal
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.execution.proc import run_capture
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.approval import ApprovalManager
from Sprout.security.engine import PolicyEngine
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace

if TYPE_CHECKING:
    from Sprout.events import EventBus


class ApplyBroker:
    """Separates sandbox writes from real workspace apply."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        approvals: ApprovalManager | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._policy = policy
        self._approvals = approvals
        self._events = events

    async def evaluate(
        self,
        proposal: ChangeProposal,
        workspace: Workspace,
        *,
        scope: DelegationScope | None = None,
    ) -> ApplyResult:
        resource = ResourceRef(
            workspace_id=workspace.id,
            path=str(workspace.root),
            kind=ResourceKind.CONFIG,
        )
        arguments = {"proposal_id": proposal.id, "risk": proposal.risk}
        request = ActionRequest(
            task_id=proposal.task_id,
            action=ActionType.GIT_COMMIT,
            resource=resource,
            arguments=arguments,
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        applied = decision.decision is AccessDecision.ALLOW
        reason = decision.reason
        if decision.decision is AccessDecision.REQUIRE_APPROVAL and self._approvals is not None:
            applied = await self._approvals.is_approved(
                ActionType.GIT_COMMIT.value, arguments, task_id=proposal.task_id
            )
            if not applied:
                reason = reason or "Apply requires an approval record"
        return ApplyResult(
            proposal_id=proposal.id,
            applied=applied,
            reason=reason,
        )

    async def apply(
        self,
        proposal: ChangeProposal,
        workspace: Workspace,
        *,
        scope: DelegationScope | None = None,
    ) -> ApplyResult:
        """Apply an approved proposal to the real workspace."""
        result = await self.evaluate(proposal, workspace, scope=scope)
        if not result.applied:
            return result

        patch = "\n".join(item.diff_text for item in proposal.diffs if item.diff_text)
        if not patch:
            return ApplyResult(proposal_id=proposal.id, applied=True, reason="No diff to apply")

        patch_path = self._write_patch(proposal.id, patch)
        try:
            # ``git apply`` is all-or-nothing for a single patch, but preflight
            # anyway so a conflict never leaves a half-applied working tree.
            code, _, stderr = await self._git(
                workspace, "apply", "--check", "--whitespace=nowarn", patch_path
            )
            if code != 0:
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=False,
                    reason=(stderr.strip() or "git apply --check failed"),
                )

            base_commit = await self._head_commit(workspace)
            code, _, stderr = await self._git(
                workspace, "apply", "--whitespace=nowarn", patch_path
            )
            if code != 0:
                detail = stderr.strip()
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=False,
                    reason=detail or "git apply failed",
                )

            files = tuple(proposal.files_changed)
            if files:
                code, _, stderr = await self._git(
                    workspace, "add", "--", *files
                )
            else:
                code, _, stderr = await self._git(workspace, "add", "-A")
            if code != 0:
                await self._undo(workspace, patch_path, files)
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=False,
                    reason=stderr.strip() or "git add failed",
                )

            summary = " ".join(
                str(proposal.metadata.get("summary", "")).split()
            )[:80]
            if summary:
                message = f"SEMA: {summary} ({proposal.id[:8]})"
            else:
                message = f"SEMA: apply change proposal {proposal.id[:8]}"
            code, _, stderr = await self._git(
                workspace, "commit", "-m", message
            )
            if code != 0:
                await self._undo(workspace, patch_path, files)
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=False,
                    reason=stderr.strip() or "git commit failed",
                )

            return ApplyResult(
                proposal_id=proposal.id,
                applied=True,
                reason="applied and committed",
                base_commit=base_commit,
                applied_commit=await self._head_commit(workspace),
            )
        finally:
            Path(patch_path).unlink(missing_ok=True)

    async def rollback(
        self,
        proposal: ChangeProposal,
        workspace: Workspace,
        *,
        scope: DelegationScope | None = None,
    ) -> ApplyResult:
        """Reverse an applied proposal using ``git apply -R``."""
        result = await self.evaluate(proposal, workspace, scope=scope)
        if not result.applied:
            return result

        applied_commit = str(proposal.metadata.get("applied_commit", ""))
        base_commit = str(proposal.metadata.get("base_commit", ""))
        if applied_commit:
            code, stdout, stderr = await self._git(
                workspace, "revert", "--no-edit", applied_commit
            )
            if code == 0:
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=True,
                    reason="reverted committed change",
                    applied_commit=applied_commit,
                )
            if base_commit:
                code, _, stderr = await self._git(
                    workspace, "reset", "--hard", base_commit
                )
                if code == 0:
                    return ApplyResult(
                        proposal_id=proposal.id,
                        applied=True,
                        reason="reset to pre-apply commit",
                        base_commit=base_commit,
                    )
            return ApplyResult(
                proposal_id=proposal.id,
                applied=False,
                reason=(stderr.strip() or f"git revert {applied_commit[:8]} failed"),
            )

        patch = "\n".join(item.diff_text for item in proposal.diffs if item.diff_text)
        if not patch:
            return ApplyResult(proposal_id=proposal.id, applied=False, reason="No diff to rollback")

        patch_path = self._write_patch(proposal.id, patch)
        try:
            code, _, stderr = await run_capture(
                "git",
                *git_args(
                    "-C",
                    str(workspace.root),
                    "apply",
                    "-R",
                    "--whitespace=nowarn",
                    patch_path,
                ),
                env=git_env(),
            )
            if code != 0:
                detail = stderr.strip()
                return ApplyResult(
                    proposal_id=proposal.id,
                    applied=False,
                    reason=detail or "git apply -R failed",
                )
        finally:
            Path(patch_path).unlink(missing_ok=True)
        return ApplyResult(proposal_id=proposal.id, applied=True, reason="rolled_back")

    async def _git(
        self, workspace: Workspace, *args: str
    ) -> tuple[int, str, str]:
        return await run_capture(
            "git",
            *git_args("-C", str(workspace.root), *args),
            env=git_env(),
        )

    async def _head_commit(self, workspace: Workspace) -> str:
        code, stdout, stderr = await self._git(workspace, "rev-parse", "HEAD")
        if code != 0:
            return ""
        return stdout.strip()

    async def _undo(
        self,
        workspace: Workspace,
        patch_path: str,
        files: tuple[str, ...],
    ) -> None:
        if files:
            await self._git(workspace, "restore", "--staged", "--", *files)
        await self._git(workspace, "apply", "-R", "--whitespace=nowarn", patch_path)

    @staticmethod
    def _write_patch(proposal_id: str, patch: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f"sprout-{proposal_id[:8]}-",
            suffix=".patch",
            delete=False,
        )
        with handle:
            handle.write(patch)
        return handle.name

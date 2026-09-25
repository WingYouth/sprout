"""Sandbox lifecycle finalization and orphan reconciliation."""

from __future__ import annotations

import logging
from pathlib import Path

from Sprout.execution.models import ChangeProposal, SandboxRef
from Sprout.orchestration.models import NodeType
from Sprout.sandbox.git_worktree import GitWorktreeSandbox
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.task.models import Task, TaskResult, TaskStatus
from Sprout.workspace.models import Workspace

logger = logging.getLogger("sprout.sandbox.lifecycle")

_TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.ROLLED_BACK,
}


class SandboxLifecycleService:
    """Removes sandbox worktrees when tasks no longer need them."""

    def __init__(self, metadata: MetadataStore | None) -> None:
        self._metadata = metadata

    async def finalize(self, task: Task, result: TaskResult) -> None:
        """Clean terminal task sandboxes.

        Waiting approval tasks keep their worktrees because apply/rollback may
        still need the branch and its pending diff.
        """
        if result.status not in _TERMINAL_TASK_STATUSES:
            return
        refs = await self._proposal_refs(task.id)
        if not refs:
            return
        workspace = await self._workspace_for_task(task)
        if workspace is None:
            return
        await self._remove_refs(workspace, refs)

    async def cleanup_proposal(self, proposal: ChangeProposal) -> None:
        """Remove a single proposal's sandbox after reject/apply/rollback."""
        if proposal.sandbox_ref is None:
            return
        task = await self._task(proposal.task_id)
        if task is None:
            return
        workspace = await self._workspace_for_task(task)
        if workspace is None:
            return
        await self._remove_refs(workspace, (proposal.sandbox_ref,))

    async def reconcile_orphans(self) -> None:
        """Remove sandbox worktrees that no active proposal references."""
        if self._metadata is None:
            return
        referenced = await self._referenced_roots()
        for workspace in await self._metadata.list_workspaces():
            await self._reconcile_workspace(workspace, referenced)

    async def _proposal_refs(self, task_id: str) -> tuple[SandboxRef, ...]:
        if self._metadata is None:
            return ()
        proposals = await self._metadata.list_change_proposals(task_id)
        return tuple(
            proposal.sandbox_ref
            for proposal in proposals
            if proposal.sandbox_ref is not None
        )

    async def _workspace_for_task(self, task: Task) -> Workspace | None:
        if self._metadata is None:
            return None
        return await self._metadata.get_workspace(task.workspace_id)

    async def _task(self, task_id: str) -> Task | None:
        if self._metadata is None:
            return None
        return await self._metadata.get_task(task_id)

    async def _referenced_roots(self) -> set[Path]:
        referenced: set[Path] = set()
        if self._metadata is None:
            return referenced
        for task in await self._metadata.list_tasks():
            for proposal in await self._metadata.list_change_proposals(task.id):
                if proposal.sandbox_ref is not None:
                    referenced.add(Path(proposal.sandbox_ref.root).resolve())
            # A task can park on an *approval* before it has minted a change
            # proposal (the verification command asks a human). Its sandbox is
            # the only place the resumed work can run, so it must be treated as
            # referenced even though no proposal row exists yet.
            if task.status in _TERMINAL_TASK_STATUSES:
                continue
            for node in await self._metadata.list_execution_nodes(task.id):
                if node.type is not NodeType.SANDBOX:
                    continue
                output = node.metadata.get("output")
                if isinstance(output, dict) and output.get("root"):
                    referenced.add(Path(str(output["root"])).resolve())
        return referenced

    async def _reconcile_workspace(
        self,
        workspace: Workspace,
        referenced: set[Path],
    ) -> None:
        parent = Path(workspace.root).resolve().parent
        if not parent.exists():
            return
        for path in parent.glob(".sprout-sprout-sandbox-*"):
            if not path.is_dir():
                continue
            root = path.resolve()
            if root in referenced:
                continue
            branch_name = path.name.removeprefix(".sprout-")
            ref = SandboxRef(
                id=path.name,
                kind="git_worktree",
                root=root,
                worktree_ref=branch_name,
            )
            await self._remove_refs(workspace, (ref,))

    async def _remove_refs(
        self,
        workspace: Workspace,
        refs: tuple[SandboxRef, ...],
    ) -> None:
        sandbox = GitWorktreeSandbox(workspace)
        for ref in refs:
            try:
                await sandbox.remove(ref)
            except Exception:
                logger.exception("Failed to remove sandbox %s", ref.root)

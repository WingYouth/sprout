"""Tests for the approval-node resume path in the execution graph."""

from __future__ import annotations

import asyncio
from pathlib import Path

from Sprout.execution.models import ChangeProposal, ChangeProposalStatus
from Sprout.runtime.nodes import NodeExecutor
from Sprout.task.models import Task
from Sprout.workspace.models import Workspace, WorkspaceKind


class _Metadata:
    """Metadata fake that returns one already-approved proposal."""

    def __init__(self, proposal: ChangeProposal) -> None:
        self._proposal = proposal
        self.saved = 0

    async def list_execution_nodes(self, task_id: str) -> list:
        return []

    async def list_change_proposals(self, task_id: str) -> list[ChangeProposal]:
        return [self._proposal]

    async def save_change_proposal(self, proposal: ChangeProposal) -> None:
        self.saved += 1
        raise AssertionError("resume must not mint a duplicate proposal")


def test_approval_node_resumes_approved_proposal_without_duplicate() -> None:
    proposal = ChangeProposal(
        task_id="task-1",
        status=ChangeProposalStatus.APPROVED,
    )
    metadata = _Metadata(proposal)
    executor = NodeExecutor(
        metadata=metadata,
        router=None,
        contexts=None,
        tools=None,
        skills=None,
        read_broker=None,
        file_broker=None,
        process_broker=None,
        apply_broker=None,
    )
    workspace = Workspace(
        id="workspace-1",
        root=Path("."),
        kind=WorkspaceKind.LOCAL_DIRECTORY,
    )
    task = Task(
        id="task-1",
        workspace_id="workspace-1",
        instruction="test",
        source="test",
    )

    async def run() -> None:
        output = await executor._approval(workspace, task)
        assert output["waiting"] is False
        assert output["status"] == ChangeProposalStatus.APPROVED.value
        assert metadata.saved == 0

    asyncio.run(run())

"""Project-facing gateway facade used by built-in CLI and Web entry points."""

from __future__ import annotations

from Sprout.execution.models import ApplyResult
from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import Task
from Sprout.workspace.models import Workspace
from Sprout.workspace.query import WorkspaceQueryResult


class ProjectGateway:
    """Unified project operations for a single built-in transport."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        transport: str,
        default_user: str,
    ) -> None:
        self._runtime = runtime
        self._gateway = RuntimeGateway(runtime, transport=transport)
        self._transport = transport
        self._default_user = default_user

    async def open_workspace(self, path: str) -> Workspace:
        return await self._runtime.open_workspace(path)

    async def list_workspaces(self):
        return await self._runtime.list_workspaces()

    async def analyze_workspace(self, workspace_id: str):
        return await self._runtime.analyze_workspace(workspace_id)

    async def plan_task(self, task_id: str):
        return await self._runtime.plan_task(task_id)

    async def query_workspace_graph(
        self,
        workspace_id: str,
        *,
        name: str = "",
        relation: str | None = None,
    ):
        analysis = await self._runtime.analyze_workspace(workspace_id)
        return analysis.query().neighbors(name, relation=relation)

    async def query_project_knowledge(
        self,
        workspace_id: str,
        *,
        query: str = "",
        kind: str | None = None,
    ):
        analysis = await self._runtime.analyze_workspace(workspace_id)
        return analysis.query().knowledge(query, kind=kind)

    async def query_workspace_symbols(
        self,
        workspace_id: str,
        *,
        kind: str | None = None,
        query: str = "",
    ):
        analysis = await self._runtime.analyze_workspace(workspace_id)
        return analysis.query().symbols(kind=kind, query=query)

    async def query_workspace_dependencies(
        self,
        workspace_id: str,
        path: str,
        *,
        direction: str = "out",
    ):
        """Dependency edges of ``path``, plus the nodes those edges touch."""
        analysis = await self._runtime.analyze_workspace(workspace_id)
        edges = analysis.query().dependencies(path, direction=direction)
        touched = {edge.source for edge in edges} | {edge.target for edge in edges}
        nodes = tuple(node for node in analysis.graph.nodes if node.id in touched)
        return WorkspaceQueryResult(nodes=nodes, edges=edges)

    async def query_workspace_subgraph(
        self,
        workspace_id: str,
        name: str,
        *,
        max_depth: int = 2,
        relation: str | None = None,
    ):
        analysis = await self._runtime.analyze_workspace(workspace_id)
        return analysis.query().subgraph(name, max_depth=max_depth, relation=relation)

    async def create_task(
        self,
        workspace_id: str,
        instruction: str,
        *,
        user_id: str | None = None,
    ) -> Task:
        # Goes through strategy planning so plan steps drive the execution
        # graph; falls back to a plain task if planning is unavailable.
        return await self._runtime.create_task_planned(
            workspace_id,
            instruction,
            actor=Principal(user_id=user_id or self._default_user),
            source=self._transport,
        )

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str,
        user_id: str | None = None,
    ) -> GatewayResponse:
        return await self._gateway.execute(
            GatewayRequest(
                transport=self._transport,
                instruction=instruction,
                caller=Principal(user_id=user_id or self._default_user),
                workspace_id=workspace_id,
            )
        )

    async def run_task(self, task_id: str) -> GatewayResponse:
        task = await self._runtime.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        result = await self._runtime.execute(task)
        return GatewayResponse(
            task_id=result.task_id,
            status=result.status.value,
            content=result.content,
            metadata=dict(result.metrics),
        )

    async def find_task(self, prefix: str) -> Task:
        task = await self._runtime.get_task(prefix)
        if task is not None:
            return task
        matches = [
            item
            for item in await self._runtime.list_tasks()
            if str(item.id).startswith(prefix)
        ]
        if len(matches) > 1:
            raise LookupError(f"Task prefix {prefix!r} matches {len(matches)} tasks")
        if not matches:
            raise LookupError(f"Task not found: {prefix}")
        return matches[0]

    async def cancel_task(self, task_id: str, *, reason: str = "") -> Task:
        task = await self.find_task(task_id)
        return await self._runtime.cancel_task(task.id, reason=reason)

    async def list_changes(self, task_id: str):
        return await self._runtime.list_change_proposals(task_id)

    async def show_proposal(self, proposal_id: str):
        proposal = await self._runtime.find_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal not found: {proposal_id}")
        return proposal

    async def find_proposal(self, prefix: str):
        proposal = await self._runtime.find_change_proposal(prefix)
        if proposal is None:
            raise LookupError(f"Proposal not found: {prefix}")
        return proposal

    async def approve_proposal(self, proposal_id: str):
        proposal = await self._runtime.find_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal not found: {proposal_id}")
        return await self._runtime.approve_change_proposal(
            proposal.id,
            decided_by=self._transport,
        )

    async def reject_proposal(self, proposal_id: str, *, reason: str = ""):
        proposal = await self._runtime.find_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal not found: {proposal_id}")
        return await self._runtime.reject_change_proposal(proposal.id, reason=reason)

    async def apply_proposal(
        self, proposal_id: str, *, allow_failing_tests: bool = False
    ) -> ApplyResult:
        proposal = await self._runtime.find_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal not found: {proposal_id}")
        return await self._runtime.apply_change_proposal(
            proposal.id,
            allow_failing_tests=allow_failing_tests,
        )

    async def rollback_proposal(self, proposal_id: str) -> ApplyResult:
        proposal = await self._runtime.find_change_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal not found: {proposal_id}")
        return await self._runtime.rollback_change_proposal(proposal.id)

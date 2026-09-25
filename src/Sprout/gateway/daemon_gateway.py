"""Daemon gateway for external HTTP/RPC clients."""

from __future__ import annotations

from Sprout.gateway.project_gateway import ProjectGateway
from Sprout.runtime.runtime import Runtime


class DaemonGateway:
    """External-facing service gateway built on the project gateway facade."""

    def __init__(self, runtime: Runtime) -> None:
        self._project = ProjectGateway(
            runtime,
            transport="daemon",
            default_user="daemon-client",
        )

    async def open_workspace(self, path: str):
        return await self._project.open_workspace(path)

    async def list_workspaces(self):
        return await self._project.list_workspaces()

    async def create_task(self, workspace_id: str, instruction: str):
        return await self._project.create_task(workspace_id, instruction)

    async def run_task(self, task_id: str):
        return await self._project.run_task(task_id)

    async def list_changes(self, task_id: str):
        return await self._project.list_changes(task_id)

"""Thin HTTP client for external CLI and business applications."""

from __future__ import annotations

from typing import Any

import httpx


class DaemonClient:
    """Calls the SEMA Daemon HTTP API without importing Runtime internals."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def open_workspace(self, path: str) -> dict[str, Any]:
        return await self._request("POST", "/api/project/workspaces", json={"path": path})

    async def create_task(self, workspace_id: str, instruction: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/project/tasks",
            json={
                "workspace_id": workspace_id,
                "instruction": instruction,
            },
        )

    async def run_task(self, task_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/project/tasks/{task_id}/run",
            json={},
        )

    async def list_changes(self, task_id: str) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/api/project/tasks/{task_id}/changes",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ):
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
        ) as client:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
            return response.json()

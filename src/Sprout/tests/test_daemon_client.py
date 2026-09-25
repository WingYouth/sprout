"""Tests for the thin daemon client."""

from __future__ import annotations

import asyncio

import httpx

from Sprout.gateway.client import DaemonClient


def test_daemon_client_routes_requests() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/project/workspaces":
            return httpx.Response(200, json={"id": "ws-1"})
        if request.url.path == "/api/project/tasks":
            return httpx.Response(200, json={"id": "task-1", "status": "created"})
        if request.url.path == "/api/project/tasks/task-1/run":
            return httpx.Response(200, json={"task_id": "task-1", "status": "waiting_approval"})
        return httpx.Response(404)

    async def run() -> None:
        transport_client = _TestDaemonClient(httpx.MockTransport(handler))
        assert await transport_client.open_workspace("/repo") == {"id": "ws-1"}
        assert await transport_client.create_task("ws-1", "explain") == {
            "id": "task-1",
            "status": "created",
        }
        assert await transport_client.run_task("task-1") == {
            "task_id": "task-1",
            "status": "waiting_approval",
        }

    asyncio.run(run())


class _TestDaemonClient(DaemonClient):
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        super().__init__("https://example.test")
        self._transport = transport

    async def _request(self, method, path, *, json=None):
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
            return response.json()

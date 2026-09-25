"""Tests for RPCGateway and RPCClient."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from Sprout.config.loader import default_settings
from Sprout.gateway.rpc_client import RPCClient
from Sprout.gateway.rpc_gateway import RPCGateway
from Sprout.runtime.factory import create_runtime


def test_rpc_gateway_dispatches_project_methods(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    settings = default_settings()
    # Defaults carry no usable model on purpose (fail loud); these tests need a
    # running runtime, so pin the offline echo provider explicitly.
    settings.model.provider = "echo"
    settings.model.model = "echo-1"
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'metadata.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "trajectory")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    # Keep the audit stream in tmp_path too: the default points at the real
    # ~/.sprout/data/audit/security.jsonl, and tests must not write there.
    settings.security.audit.path = str(tmp_path / "security.jsonl")

    async def run() -> None:
        runtime = create_runtime(settings)
        workspace = await runtime.open_workspace(tmp_path)
        gateway = RPCGateway(runtime)

        created = await gateway.handle(
            {
                "id": "1",
                "method": "task.create",
                "params": {
                    "workspace_id": workspace.id,
                    "instruction": "explain this project",
                },
            }
        )
        assert "result" in created

        run_result = await gateway.handle(
            {
                "id": "2",
                "method": "task.run",
                "params": {"task_id": created["result"]["id"]},
            }
        )
        assert run_result["result"]["status"] in {"waiting_approval", "completed"}
        await runtime.stop()

    asyncio.run(run())


def test_rpc_client_calls_http_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "rpc-1", "result": {"status": "completed"}})

    async def run() -> None:
        test_client = _TestRPCClient(httpx.MockTransport(handler))
        response = await test_client.call("task.run", {"task_id": "task-1"})
        assert response["result"]["status"] == "completed"

    asyncio.run(run())


def test_rpc_gateway_returns_standard_error_codes(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)
    gateway = RPCGateway(runtime)

    async def run() -> None:
        response = await gateway.handle(
            {
                "id": "3",
                "method": "task.run",
                "params": {},
            }
        )
        assert response["error"]["code"] == "INVALID_PARAMS"

    asyncio.run(run())


class _TestRPCClient(RPCClient):
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        super().__init__("https://example.test")
        self._transport = transport

    async def call(self, method, params=None):
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                "/api/rpc",
                json={"id": "rpc-1", "method": method, "params": params or {}},
            )
            response.raise_for_status()
            return response.json()


def _runtime_for_test(root: Path):
    settings = default_settings()
    # Defaults carry no usable model on purpose (fail loud); these tests need a
    # running runtime, so pin the offline echo provider explicitly.
    settings.model.provider = "echo"
    settings.model.model = "echo-1"
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{root / 'metadata.db'}"
    settings.storage.trajectory_dir = str(root / "trajectory")
    settings.storage.blobs_dir = str(root / "blobs")
    # Keep the audit stream in tmp_path too: the default points at the real
    # ~/.sprout/data/audit/security.jsonl, and tests must not write there.
    settings.security.audit.path = str(root / "security.jsonl")
    return create_runtime(settings)

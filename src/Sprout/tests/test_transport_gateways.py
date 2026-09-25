"""Smoke tests for CLI, Web, and MCP gateway adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path

from Sprout.config.loader import default_settings
from Sprout.gateway.transport_gateways import CLIGateway, MCPGateway, WebGateway
from Sprout.runtime.factory import create_runtime


def test_transport_gateways_execute_task(tmp_path: Path) -> None:
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

        cli_response = await CLIGateway(runtime).execute(
            "explain this project",
            workspace_id=workspace.id,
        )
        web_response = await WebGateway(runtime).execute(
            "explain this project",
            workspace_id=workspace.id,
        )
        mcp_response = await MCPGateway(runtime).execute(
            "explain this project",
            workspace_id=workspace.id,
        )

        assert cli_response.status in {"waiting_approval", "completed"}
        assert web_response.status in {"waiting_approval", "completed"}
        assert mcp_response.status in {"waiting_approval", "completed"}
        await runtime.stop()

    asyncio.run(run())

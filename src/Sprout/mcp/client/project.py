"""Helpers for recognizing Project Runtime MCP capabilities."""

from __future__ import annotations

from typing import Any

PROJECT_TOOL_PREFIXES = (
    "workspace_",
    "task_",
    "sandbox_",
    "trajectory_",
    "proposal_",
)


def project_tool_names(discovery_summary: dict[str, list[dict[str, Any]]]) -> list[str]:
    names: list[str] = []
    for tool in discovery_summary.get("tools", []):
        name = tool.get("name", "")
        if name.startswith(PROJECT_TOOL_PREFIXES):
            names.append(name)
    return names

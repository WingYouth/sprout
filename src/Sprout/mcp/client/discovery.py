"""Discovery helpers for external MCP servers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.mcp.client.connection import MCPConnection


async def discover(connection: MCPConnection) -> dict[str, list[dict[str, Any]]]:
    """Summarize what one external MCP server offers (tools/resources/prompts)."""
    summary: dict[str, list[dict[str, Any]]] = {"tools": [], "resources": [], "prompts": []}
    try:
        for tool in await connection.list_tools():
            summary["tools"].append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {},
                }
            )
    except Exception:  # noqa: BLE001 - discovery is best-effort
        pass
    try:
        for resource in await connection.list_resources():
            summary["resources"].append(
                {
                    "uri": resource.uri,
                    "name": resource.name,
                    "description": resource.description or "",
                }
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        for prompt in await connection.list_prompts():
            summary["prompts"].append(
                {"name": prompt.name, "description": prompt.description or ""}
            )
    except Exception:  # noqa: BLE001
        pass
    return summary

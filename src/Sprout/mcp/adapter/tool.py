"""MCP tool adapter: remote MCP tools become uniform Sprout tools.

External MCP Tool -> MCPToolAdapter -> ToolSpec -> ToolRegistry -> AgentContext
Python, HTTP, and MCP tools all end up behind the same interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec

if TYPE_CHECKING:
    from Sprout.mcp.client.connection import MCPConnection


def _content_to_text(content: Any) -> str:
    """Extract readable text from an MCP CallToolResult content list."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    items = content if isinstance(content, (list, tuple)) else [content]
    for item in items:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif item is not None:
            parts.append(str(item))
    return "\n".join(parts)


@dataclass(slots=True)
class MCPToolAdapter:
    """Converts external MCP tool descriptors into uniform ToolSpec objects."""

    default_risk_level: str = "medium"

    def to_tool_spec(self, remote_tool: Any, *, server_name: str = "") -> ToolSpec:
        name = remote_tool.name
        prefixed = f"{server_name}_{name}" if server_name else name
        schema = remote_tool.inputSchema or {}
        return ToolSpec(
            name=prefixed,
            description=remote_tool.description or f"MCP tool {name!r} from {server_name!r}",
            input_schema=dict(schema) if isinstance(schema, Mapping) else {},
            risk_level=self.default_risk_level,
        )

    def to_tool(self, connection: MCPConnection, remote_tool: Any) -> MCPTool:
        return MCPTool(
            connection=connection,
            spec=self.to_tool_spec(remote_tool, server_name=connection.name),
            remote_name=remote_tool.name,
        )


@dataclass(slots=True)
class MCPTool:
    """A Tool implementation that proxies invoke() to a remote MCP server."""

    connection: MCPConnection
    spec: ToolSpec
    remote_name: str

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            result = await self.connection.call_tool(self.remote_name, dict(arguments))
        except Exception as exc:  # noqa: BLE001 - remote errors become tool failures
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")
        is_error = bool(getattr(result, "isError", False))
        text = _content_to_text(getattr(result, "content", result))
        if is_error:
            return ToolResult.failure(text or "Remote MCP tool reported an error")
        return ToolResult.success(text, data={"server": self.connection.name})

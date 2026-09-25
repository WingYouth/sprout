"""MCP client package."""

from Sprout.mcp.client.client import MCPClientManager, attach_mcp_clients
from Sprout.mcp.client.connection import MCPConnection
from Sprout.mcp.client.discovery import discover
from Sprout.mcp.client.project import PROJECT_TOOL_PREFIXES, project_tool_names

__all__ = [
    "MCPClientManager",
    "MCPConnection",
    "PROJECT_TOOL_PREFIXES",
    "attach_mcp_clients",
    "discover",
    "project_tool_names",
]

"""MCP adapters: external capabilities become uniform Sprout capabilities."""

from Sprout.mcp.adapter.prompt import to_prompt_template
from Sprout.mcp.adapter.resource import RemoteResource, to_remote_resource
from Sprout.mcp.adapter.tool import MCPTool, MCPToolAdapter

__all__ = [
    "MCPTool",
    "MCPToolAdapter",
    "RemoteResource",
    "to_prompt_template",
    "to_remote_resource",
]

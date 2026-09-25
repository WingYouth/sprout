"""MCP server package."""

from Sprout.mcp.server.prompts import PROMPT_DEFINITIONS
from Sprout.mcp.server.resources import RESOURCE_DEFINITIONS
from Sprout.mcp.server.server import (
    DESCRIPTION,
    build_server,
    create_default_server,
    main,
    server_definitions,
)
from Sprout.mcp.server.tools import TOOL_DEFINITIONS

__all__ = [
    "DESCRIPTION",
    "PROMPT_DEFINITIONS",
    "RESOURCE_DEFINITIONS",
    "TOOL_DEFINITIONS",
    "build_server",
    "create_default_server",
    "main",
    "server_definitions",
]

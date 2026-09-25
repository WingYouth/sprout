"""Model Context Protocol integration for SEAM Sprout (server + client + adapters)."""

from Sprout.mcp.client.client import MCPClientManager, attach_mcp_clients
from Sprout.mcp.client.connection import MCPConnection
from Sprout.mcp.server.server import (
    build_server,
    create_default_server,
    main,
    server_definitions,
)

__all__ = [
    "MCPClientManager",
    "MCPConnection",
    "attach_mcp_clients",
    "build_server",
    "create_default_server",
    "main",
    "server_definitions",
]

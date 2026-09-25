"""MCP Client: let Sprout use external MCP servers as tool sources.

External MCP Server -> Sprout MCP Client -> MCPToolAdapter -> ToolRegistry -> Agent
The agent only ever sees uniform ToolSpec objects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from Sprout.mcp.adapter.tool import MCPTool, MCPToolAdapter
from Sprout.mcp.client.connection import MCPConnection

if TYPE_CHECKING:
    from Sprout.config.settings import MCPSettings, Settings
    from Sprout.runtime.runtime import Runtime

logger = logging.getLogger("sprout.mcp.client")


class MCPClientManager:
    """Starts, tracks, and stops external MCP server connections."""

    def __init__(self, connections: dict[str, MCPConnection] | None = None) -> None:
        self._connections: dict[str, MCPConnection] = connections or {}

    @classmethod
    def from_settings(cls, settings: MCPSettings) -> MCPClientManager:
        connections = {
            client.name: MCPConnection(
                name=client.name, command=client.command, args=client.args, env=client.env
            )
            for client in settings.clients
        }
        return cls(connections)

    @property
    def connections(self) -> dict[str, MCPConnection]:
        return dict(self._connections)

    def connection(self, name: str) -> MCPConnection:
        return self._connections[name]

    async def start(self) -> None:
        for connection in self._connections.values():
            try:
                await connection.start()
            except Exception:  # noqa: BLE001 - one bad server must not block startup
                logger.exception("Failed to start MCP connection %r", connection.name)

    async def stop(self) -> None:
        for connection in self._connections.values():
            await connection.stop()

    async def collect_tools(self) -> list[MCPTool]:
        """List every remote tool, adapted to the uniform Tool interface."""
        adapter = MCPToolAdapter()
        tools: list[MCPTool] = []
        for connection in self._connections.values():
            try:
                remote_tools = await connection.list_tools()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to list tools from %r", connection.name)
                continue
            for remote in remote_tools:
                tools.append(adapter.to_tool(connection, remote))
        return tools


async def attach_mcp_clients(runtime: Runtime, settings: Settings) -> MCPClientManager | None:
    """Entry-point helper: spawn configured external servers, register their tools.

    Called by CLI/Web/MCP entries after ``create_runtime``; the runtime factory
    itself stays free of MCP imports.
    """
    if not settings.mcp.clients:
        return None
    manager = MCPClientManager.from_settings(settings.mcp)
    await manager.start()
    registered = 0
    for tool in await manager.collect_tools():
        runtime.tools.register(tool)
        registered += 1
    logger.info("Registered %d MCP tools from %d server(s)", registered, len(manager.connections))
    return manager

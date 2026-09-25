"""MCP Server: expose SEAM Sprout to external MCP clients (Claude, Codex, ...).

External MCP Client -> SEAM Sprout MCP Server -> Runtime.handle()
The server never touches agents, storage internals, or the growth layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from Sprout.config.loader import load_settings
from Sprout.mcp.server.prompts import PROMPT_DEFINITIONS, register_prompts
from Sprout.mcp.server.resources import RESOURCE_DEFINITIONS, register_resources
from Sprout.mcp.server.tools import TOOL_DEFINITIONS, register_tools

if TYPE_CHECKING:
    from Sprout.runtime.runtime import Runtime

DESCRIPTION = (
    "SEAM Sprout: an embeddable agent runtime with skills, knowledge search, "
    "and an auditable growth layer."
)


def build_server(runtime: Runtime) -> MCPServer:
    """Assemble the MCP server (tools + resources + prompts) around a runtime."""
    server = MCPServer(name="SEAM Sprout", instructions=DESCRIPTION)
    register_tools(server, runtime)
    register_resources(server, runtime)
    register_prompts(server)
    return server


def server_definitions() -> dict[str, list[dict]]:
    """Static metadata of everything this server exposes (used by `sprout mcp inspect`)."""
    return {
        "tools": TOOL_DEFINITIONS,
        "resources": RESOURCE_DEFINITIONS,
        "prompts": PROMPT_DEFINITIONS,
    }


def create_default_server() -> MCPServer:
    """Build a server on a runtime assembled from the default settings."""
    from Sprout.runtime.factory import create_runtime

    settings = load_settings()
    runtime = create_runtime(settings)
    if settings.evolution.enabled:
        from Sprout.evolution import attach_evolution

        attach_evolution(runtime, settings)
    return build_server(runtime)


def main() -> None:
    """Run the MCP server over stdio (entry point: ``sprout-mcp`` / ``sprout mcp serve``)."""
    from Sprout.orchestration.terminal.ensure import ensure_temporal
    from Sprout.storage.bootstrap import ensure_storage_sync

    ensure_temporal(announce=False)
    ensure_storage_sync(load_settings())
    server = create_default_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

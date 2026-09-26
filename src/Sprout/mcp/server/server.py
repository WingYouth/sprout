"""MCP Server: expose SEAM Sprout to external MCP clients (Claude, Codex, ...).

External MCP Client -> SEAM Sprout MCP Server -> Runtime.handle()
The server never touches agents, storage internals, or the growth layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer

from Sprout.config.loader import load_settings
from Sprout.mcp.server.prompts import PROMPT_DEFINITIONS, register_prompts
from Sprout.mcp.server.resources import RESOURCE_DEFINITIONS, register_resources
from Sprout.mcp.server.tools import TOOL_DEFINITIONS, register_tools

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime

DESCRIPTION = (
    "SEAM Sprout: an embeddable agent runtime with skills, knowledge search, "
    "and an auditable growth layer."
)


class LazyRuntime:
    """Defer Runtime assembly until a MCP operation actually needs it."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._runtime: Runtime | None = None

    def _get_runtime(self) -> Runtime:
        if self._runtime is None:
            from Sprout.runtime.factory import create_runtime

            settings = self._settings or load_settings()
            runtime = create_runtime(settings)
            if settings.evolution.enabled:
                from Sprout.evolution import attach_evolution

                attach_evolution(runtime, settings)
            self._runtime = runtime
        return self._runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_runtime(), name)


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
    return build_server(LazyRuntime())


def main() -> None:
    """Run the MCP server over stdio (entry point: ``sprout-mcp`` / ``sprout mcp serve``)."""
    # Stdio MCP has a strict contract: stdout belongs to JSON-RPC frames from
    # the first byte. Keep boot checks out of this path so clients can
    # initialize and inspect the surface even when optional operational services
    # such as Temporal or Docker-backed storage lanes are down. Tool calls still
    # surface runtime/service errors at the operation boundary.
    server = create_default_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

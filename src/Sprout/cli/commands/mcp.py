"""``sprout mcp``: run and inspect the MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui

app = typer.Typer(help="MCP server entry points.", no_args_is_help=True)


def _connection_hint() -> str:
    """Human-facing hint for running the stdio server from an MCP client."""
    cwd = Path.cwd().as_posix()
    return (
        "SEAM Sprout MCP server is ready on stdio.\n"
        "Add this server to your MCP client configuration:\n"
        "{\n"
        '  "mcpServers": {\n'
        '    "seam-sprout": {\n'
        '      "command": "uv",\n'
        '      "args": ["run", "sprout", "mcp", "serve"],\n'
        f'      "cwd": "{cwd}"\n'
        "    }\n"
        "  }\n"
        "}\n"
        "Then restart or reload your MCP client.\n"
        "This command is not an HTTP server; the MCP client should launch it "
        "and communicate through stdin/stdout.\n"
        "Press Ctrl-D or Ctrl-C to stop this manual session.\n"
        "Use `uv run sprout mcp inspect` to list tools, resources, and prompts."
    )


def _maybe_show_connection_hint() -> None:
    """Show connection help only for humans, never for piped MCP clients."""
    if sys.stdin.isatty() and sys.stderr.isatty():
        typer.echo(_connection_hint(), err=True)


@app.command()
def serve(
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to sprout.toml."),
    ] = None,
) -> None:
    """Run the MCP server over stdio.

    This is the long-running entry point for Claude, Codex, and other MCP
    clients. It exposes only the safe runtime surface.
    """
    import os

    if config:
        os.environ["SPROUT_CONFIG"] = config
    from Sprout.mcp.server.server import main as serve_mcp

    _maybe_show_connection_hint()
    serve_mcp()


@app.command()
def inspect(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print definitions as machine-readable JSON."),
    ] = False,
) -> None:
    """Show the tools, resources, and prompts this server would expose.

    Use this before configuring an MCP client so you can see exact names and
    descriptions of the safe surface.
    """
    from Sprout.mcp.server.server import server_definitions

    definitions = server_definitions()
    if as_json:
        typer.echo(json.dumps(definitions, indent=2, ensure_ascii=False))
        return

    ui.banner("SEAM Sprout MCP Server", subtitle="Safe model-facing surface")
    for kind, entries in definitions.items():
        ui.section(f"{kind.capitalize()} ({len(entries)})")
        if not entries:
            typer.echo(ui.muted("  None"))
        for entry in entries:
            name = entry.get("name") or entry.get("uri")
            description = entry.get("description", "")
            typer.echo(ui.bullet(name, description))
    typer.echo("")
    typer.echo(ui.muted("Run `sprout mcp serve` to start this server over stdio."))

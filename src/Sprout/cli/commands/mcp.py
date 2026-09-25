"""``sprout mcp``: run and inspect the MCP server."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from Sprout.cli import ui

app = typer.Typer(help="MCP server entry points.", no_args_is_help=True)


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

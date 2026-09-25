"""``sprout info``: version, configuration, and entry points."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer

from Sprout.cli import ui


def info(
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Path to sprout.toml. Defaults to sprout.toml, then ~/.sprout/sprout.toml.",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the snapshot as machine-readable JSON."),
    ] = False,
) -> None:
    """Show the installed version and the effective runtime configuration.

    Use this as the first diagnostic step: it shows which model, storage,
    security, MCP, evolution, and web settings the runtime will actually use.
    """
    from Sprout.config.loader import dump_settings, load_settings

    try:
        package_version = version("seam-sprout")
    except PackageNotFoundError:  # pragma: no cover
        package_version = "0.0.0.dev0"
    settings = load_settings(config)
    payload = {
        "version": package_version,
        "settings": dump_settings(settings),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    ui.banner(
        f"SEAM Sprout {package_version}",
        subtitle="Runtime and configuration snapshot",
    )

    ui.section("Runtime")
    typer.echo(ui.key_value("default agent", settings.runtime.default_agent))
    typer.echo(ui.key_value("max tool steps", settings.runtime.max_tool_steps))
    typer.echo(ui.key_value("turn limit", settings.runtime.session_turn_limit))

    ui.section("Model")
    typer.echo(
        ui.key_value(
            "provider",
            f"{settings.model.provider} ({settings.model.model})",
        )
    )
    typer.echo(ui.key_value("base URL", settings.model.base_url))
    typer.echo(ui.key_value("API key env", settings.model.api_key_env))
    typer.echo(ui.key_value("timeout", f"{settings.model.timeout_seconds:.0f}s"))
    temperature = (
        "default" if settings.model.temperature is None else settings.model.temperature
    )
    typer.echo(ui.key_value("temperature", temperature))

    ui.section("Storage")
    typer.echo(ui.key_value("core", settings.storage.core))
    typer.echo(ui.key_value("conversation", settings.storage.conversation))
    typer.echo(ui.key_value("knowledge", settings.storage.knowledge))
    typer.echo(ui.key_value("audit", settings.storage.audit))
    observations = (
        f"{settings.storage.observations.dsn} (enabled)"
        if settings.storage.observations.enabled
        else "disabled"
    )
    typer.echo(ui.key_value("audit events", observations))
    typer.echo(ui.key_value("usage", settings.storage.usage))
    typer.echo(ui.key_value("projects", settings.storage.project_root))
    typer.echo(ui.key_value("cache", settings.storage.cache))
    typer.echo(ui.key_value("blobs", settings.storage.blobs_dir))

    ui.section("Security")
    typer.echo(
        ui.key_value(
            "medium risk",
            "allowed" if settings.security.allow_medium_risk else "blocked",
        )
    )
    typer.echo(
        ui.key_value(
            "approval",
            "required" if settings.security.require_approval else "not configured",
        )
    )

    ui.section("MCP")
    typer.echo(
        ui.key_value(
            "server",
            f"{'enabled' if settings.mcp.server.enabled else 'disabled'} "
            f"/ {settings.mcp.server.transport}",
        )
    )
    typer.echo(ui.key_value("clients", len(settings.mcp.clients)))
    for client in settings.mcp.clients:
        command = " ".join([client.command, *client.args])
        typer.echo(ui.bullet(client.name, command))

    ui.section("Evolution")
    evolution_state = (
        "enabled"
        if settings.evolution.enabled
        else "disabled"
    )
    typer.echo(ui.key_value("state", evolution_state))
    if settings.evolution.enabled:
        typer.echo(
            ui.key_value(
                "approval",
                "required" if settings.evolution.approval_required else "auto",
            )
        )
        typer.echo(ui.key_value("level", settings.evolution.level))

    ui.section("Web")
    typer.echo(
        ui.key_value("endpoint", f"http://{settings.web.host}:{settings.web.port}")
    )

    ui.section("Entry Points")
    typer.echo(
        ui.bullet("chat", "Send a one-shot message or start interactive chat")
    )
    typer.echo(ui.bullet("serve", "Run the HTTP/WebSocket API and static frontend"))
    typer.echo(ui.bullet("project", "Operate local workspaces, tasks, and proposals"))
    typer.echo(ui.bullet("remote", "Operate a remote SEMA service over HTTP/RPC"))
    typer.echo(ui.bullet("mcp", "Serve or inspect the MCP server"))
    typer.echo(ui.bullet("storage", "Initialize and inspect local stores"))
    typer.echo(ui.bullet("evolution", "Inspect and drive the growth layer"))
    typer.echo(ui.bullet("info", "Show this runtime snapshot"))
    typer.echo("")
    typer.echo(ui.muted("Run `sprout <command> --help` for detailed usage."))

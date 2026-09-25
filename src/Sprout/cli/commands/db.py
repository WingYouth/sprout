"""Unified database CLI for storage and session operations."""

from __future__ import annotations

from typing import Annotated

import typer

from Sprout.cli.commands import session, storage

app = typer.Typer(help="Unified local database operations.", no_args_is_help=True)


@app.command("init")
def init(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    no_chmod: Annotated[
        bool,
        typer.Option("--no-chmod", help="Skip chmod 0600 on databases."),
    ] = False,
    all_lanes: Annotated[
        bool,
        typer.Option(
            "--all/--no-all",
            help="Initialize all six lanes with local defaults.",
        ),
    ] = True,
) -> None:
    """Initialize every configured database."""
    storage.init(config=config, no_chmod=no_chmod, all_lanes=all_lanes)


@app.command("status")
def status(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show only the running/healthy status for every database lane."""
    storage.health(config=config, all_lanes=True)


@app.command("backup")
def backup(
    target: Annotated[str, typer.Argument(help="Backup destination directory.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Back up all SQLite databases."""
    storage.backup(target=target, config=config)


@app.command("restore")
def restore(
    source: Annotated[str, typer.Argument(help="Source backup directory.")],
    target: Annotated[
        str | None,
        typer.Option("--target", help="Restore destination directory (required)."),
    ] = None,
) -> None:
    """Restore SQLite databases from a backup directory."""
    storage.restore(source=source, target=target)


@app.command("session-new")
def session_new(
    user: Annotated[str, typer.Option("--user", help="User id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Create a new session."""
    session.new_cmd(user=user, config=config)


@app.command("session-history")
def session_history(
    session_id: Annotated[str, typer.Argument(help="Session id.")],
    limit: Annotated[int, typer.Option("--limit", help="Max turns.")] = 20,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show recent turns for a session."""
    session.history_cmd(session_id=session_id, limit=limit, config=config)


@app.command("session-search")
def session_search(
    query: Annotated[str, typer.Argument(help="FTS5 query.")],
    session_id: Annotated[
        str | None, typer.Option("--session", help="Limit to one session.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max hits.")] = 10,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Search session turns."""
    session.search_cmd(
        query=query,
        session=session_id,
        limit=limit,
        config=config,
    )


@app.command("session-delete")
def session_delete(
    session_id: Annotated[str, typer.Argument(help="Session id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Delete a session and derived artifacts."""
    session.delete_cmd(session_id=session_id, config=config)

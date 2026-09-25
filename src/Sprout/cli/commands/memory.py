"""``sprout memory`` — manage MEMORY.md (session) and USER.md (user profile).

Subcommands mirror the Hermes ``memory`` tool actions:

- ``list``     — show facts in either store
- ``add``      — append a new fact (rejected if over the char cap)
- ``replace``  — substring match + in-place edit
- ``remove``   — substring match + drop
- ``status``   — char usage + file paths

The memory backend is the file-system store under ``settings.memory.home``;
each session has its own ``MEMORY-<id>.md`` and the user has ``USER.md``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.memory.backends.file_system import FileSystemMemoryStore
from Sprout.memory.models import SessionFact, UserFact

app = typer.Typer(
    name="memory",
    help="Curate MEMORY.md (per-session) and USER.md (per-user).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _store(config: str | None) -> FileSystemMemoryStore:
    settings = load_settings(config)
    return FileSystemMemoryStore(settings.memory.home)


@app.command(name="list")
def list_cmd(
    session: Annotated[
        str | None, typer.Option("--session", help="List MEMORY.md for this session.")
    ] = None,
    user: Annotated[
        bool, typer.Option("--user", help="List USER.md instead of session facts.")
    ] = False,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """List every fact in MEMORY.md (or USER.md with --user)."""
    store = _store(config)
    if user:
        facts = asyncio.run(store.list_user_facts("default"))
        ui.banner("USER.md", subtitle="Per-user profile facts")
        for fact in facts:
            typer.echo(ui.key_value(fact.key, fact.value))
        return
    if session is None:
        raise typer.BadParameter("Provide --session <id> (or --user).")
    facts = asyncio.run(store.list_session_facts(session))
    ui.banner(f"MEMORY.md [{session}]", subtitle="Per-session facts")
    for fact in facts:
        typer.echo(ui.key_value(fact.key, fact.value))


@app.command(name="add")
def add_cmd(
    key: Annotated[str, typer.Option("--key", help="Fact key (short label).")],
    value: Annotated[str, typer.Option("--value", help="Fact body.")],
    session: Annotated[
        str | None, typer.Option("--session", help="Target session id.")
    ] = None,
    user: Annotated[
        bool, typer.Option("--user", help="Add to USER.md instead.")
    ] = False,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Append one fact; refused with the current entry when over the cap."""
    settings = load_settings(config)
    store = _store(config)
    from datetime import UTC, datetime

    cap = (
        settings.memory.user_char_limit
        if user
        else settings.memory.session_char_limit
    )
    if user:
        fact = UserFact(
            user_id=session or "default", key=key, value=value,
            updated_at=datetime.now(UTC),
        )
        rejected = asyncio.run(store.add_user_fact(fact, char_limit=cap))
    else:
        if session is None:
            raise typer.BadParameter("Provide --session <id> (or --user).")
        fact = SessionFact(
            session_id=session, key=key, value=value,
            updated_at=datetime.now(UTC),
        )
        rejected = asyncio.run(store.add_session_fact(fact, char_limit=cap))
    if rejected is not None:
        typer.echo(ui.muted(f"Rejected: {rejected.value[:80]}…"))
        raise typer.Exit(code=2)
    typer.echo(ui.muted("ok"))


@app.command(name="replace")
def replace_cmd(
    old: Annotated[str, typer.Option("--old", help="Substring to match.")],
    key: Annotated[str, typer.Option("--key", help="New fact key.")],
    value: Annotated[str, typer.Option("--value", help="New fact body.")],
    session: Annotated[
        str | None, typer.Option("--session", help="Target session id.")
    ] = None,
    user: Annotated[
        bool, typer.Option("--user", help="Replace in USER.md instead.")
    ] = False,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    settings = load_settings(config)
    store = _store(config)
    from datetime import UTC, datetime

    cap = (
        settings.memory.user_char_limit
        if user
        else settings.memory.session_char_limit
    )
    if user:
        fact = UserFact(
            user_id=session or "default", key=key, value=value,
            updated_at=datetime.now(UTC),
        )
        ok = asyncio.run(
            store.replace_user_fact("default", old, fact, char_limit=cap)
        )
    else:
        if session is None:
            raise typer.BadParameter("Provide --session <id> (or --user).")
        fact = SessionFact(
            session_id=session, key=key, value=value,
            updated_at=datetime.now(UTC),
        )
        ok = asyncio.run(
            store.replace_session_fact(session, old, fact, char_limit=cap)
        )
    if not ok:
        raise typer.BadParameter("No match or rejected by scanner / cap.")
    typer.echo(ui.muted("ok"))


@app.command(name="remove")
def remove_cmd(
    substring: Annotated[str, typer.Argument(help="Substring to match.")],
    session: Annotated[
        str | None, typer.Option("--session", help="Target session id.")
    ] = None,
    user: Annotated[
        bool, typer.Option("--user", help="Remove from USER.md instead.")
    ] = False,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    store = _store(config)
    if user:
        removed = asyncio.run(store.remove_user_fact("default", substring))
    else:
        if session is None:
            raise typer.BadParameter("Provide --session <id> (or --user).")
        removed = asyncio.run(store.remove_session_fact(session, substring))
    typer.echo(ui.muted(f"removed {removed} entries"))


@app.command(name="status")
def status_cmd(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    settings = load_settings(config)
    store = _store(config)
    home = store.home
    ui.banner("Memory", subtitle=str(home))
    memory_path = home / "MEMORY.md"
    user_path = home / "USER.md"
    sessions_dir = home / "sessions"
    for path in (memory_path, user_path):
        chars = path.stat().st_size if path.exists() else 0
        typer.echo(ui.key_value(path.name, f"{chars} chars"))
    typer.echo(
        ui.key_value("session cap", str(settings.memory.session_char_limit))
    )
    typer.echo(
        ui.key_value("user cap", str(settings.memory.user_char_limit))
    )
    typer.echo(
        ui.key_value("session files", str(sum(1 for _ in sessions_dir.glob("*.md"))))
    )
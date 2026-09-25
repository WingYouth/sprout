"""``sprout session`` — search, compact, split, and delete sessions.

The four commands mirror the operational primitives the heartwood compactor
already supports, but they're exposed here so an operator can drive them
without booting the full runtime.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.runtime.factory import create_runtime
from Sprout.storage.bundle import create_storage

app = typer.Typer(
    name="session",
    help="Search, compact, split, and delete sessions.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _bundle(config: str | None):
    settings = load_settings(config)
    from Sprout.storage.local.sqlite.driver import SqlitePragmas

    sqlite_cfg = settings.sqlite
    pragmas = SqlitePragmas(
        busy_timeout_ms=sqlite_cfg.busy_timeout_ms,
        synchronous=sqlite_cfg.synchronous,
        readers=sqlite_cfg.readers,
    )
    return create_storage(settings.storage, pragmas=pragmas, memory_settings=settings.memory)


@app.command(name="search")
def search_cmd(
    query: Annotated[str, typer.Argument(help="FTS5 query.")],
    session: Annotated[
        str | None, typer.Option("--session", help="Limit to one session.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max hits.")] = 10,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Full-text search across turns (FTS5 over sprout_conversation.db)."""
    bundle = _bundle(config)
    try:
        search = bundle.session_search
        if search is None:
            raise typer.BadParameter("SessionSearch is not wired for this storage.")
        hits = asyncio.run(
            search.search(query, limit=limit, session_id=session)
        )
    finally:
        asyncio.run(bundle.close())
    if not hits:
        typer.echo(ui.muted("no hits"))
        return
    ui.banner(f"Search: {query!r}", subtitle=f"{len(hits)} hits")
    for hit in hits:
        typer.echo(
            f"  [{hit.session_id} seq={hit.turn_seq}] {hit.snippet}"
        )


@app.command(name="compact")
def compact_cmd(
    session_id: Annotated[str, typer.Argument(help="Session id to compact.")],
    threshold_seq: Annotated[
        int | None,
        typer.Option("--through-seq", help="Compress turns up to this seq."),
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Roll the session's turns into a digest and persist it in the memory layer."""
    from Sprout.memory.compactor import SessionCompactor

    runtime = create_runtime(load_settings(config))
    try:
        memory = runtime.storage.memory
        if memory is None:
            typer.echo(ui.muted("memory layer disabled; nothing to compact"))
            return
        compactor = SessionCompactor(
            runtime.storage.session_store(),
            memory,
        )
        summary = asyncio.run(
            compactor.roll(session_id, threshold_seq or 10**9)
        )
    finally:
        asyncio.run(runtime.stop())
    if summary is None:
        typer.echo(ui.muted("nothing to compact"))
    else:
        typer.echo(ui.muted(f"summary seq={summary.seq} covers through {summary.covered_through}"))


@app.command(name="new")
def new_cmd(
    user: Annotated[str, typer.Option("--user", help="User id for the new session.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Create a fresh session id (Hermes ``/new`` semantics)."""
    runtime = create_runtime(load_settings(config))
    try:
        session = asyncio.run(runtime.create_session(user))
    finally:
        asyncio.run(runtime.stop())
    typer.echo(session.id)


@app.command(name="delete")
def delete_cmd(
    session_id: Annotated[str, typer.Argument(help="Session id to delete.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Cascade-delete a session and every derived artifact."""
    bundle = _bundle(config)
    try:
        report = asyncio.run(bundle.delete_session_cascade(session_id))
    finally:
        asyncio.run(bundle.close())
    typer.echo(ui.muted(str(report)))


@app.command(name="history")
def history_cmd(
    session_id: Annotated[str, typer.Argument(help="Session id.")],
    limit: Annotated[int, typer.Option("--limit", help="Max turns.")] = 20,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show the recent turns of one session."""
    bundle = _bundle(config)
    try:
        turns = asyncio.run(bundle.session_store().recent_turns(session_id, limit=limit))
    finally:
        asyncio.run(bundle.close())
    for turn in turns:
        typer.echo(f"[seq {turn.seq}] {turn.role}: {turn.content[:120]}")

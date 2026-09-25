"""``sprout storage``: reserve and inspect local databases."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui

app = typer.Typer(help="Local storage management.", no_args_is_help=True)


def _lanes_payload(report) -> dict:
    """Shared JSON shape for ``init`` and ``check``."""
    return {
        # `ok` mirrors the exit code exactly, so a consumer cannot read "true"
        # from a run that exited non-zero (no fan-out, stale schema, a dead lane).
        "ok": report.status == 0,
        "status": report.status,
        "context": dict(report.context),
        "lanes": [
            {"lane": lane.name, "detail": lane.wrote, "saw": lane.saw, "ok": lane.ok}
            for lane in report.lanes
        ],
        "notes": report.notes,
        "skipped": report.skipped,
        "lane_errors": report.lane_errors,
    }


def _lane_progress(name: str, ok: bool) -> None:
    state = "healthy" if ok else "failed"
    typer.echo(f"{state:<8} {name}")


def _lane_progress_for(*, as_json: bool):
    """The progress renderer, silenced when the payload is machine-readable.

    The callback fires while the lanes are being verified — i.e. *before* the
    ``--json`` branch is reached — so printing here put six ``healthy ...``
    lines ahead of the JSON document and made ``storage check --json``
    unparseable. Human output keeps the live progress; JSON mode says nothing
    until it has the whole report.
    """
    if as_json:
        return None
    return _lane_progress


def _progress_note_for(*, as_json: bool):
    """Print a muted progress line — except in JSON mode, where it must not.

    ``ui.muted`` returns a styled string rather than printing it, so callers
    have to wrap it in ``typer.echo``.
    """
    if as_json:
        return lambda message: None
    return lambda message: typer.echo(ui.muted(message))


def _render_lanes(report) -> None:
    """Shared lane table for ``init`` and ``check``."""
    ui.section("Lanes")
    if not report.lanes:
        typer.echo(ui.muted("No lane was inspected."))
    for lane in report.lanes:
        tag = (
            typer.style("[  ok]", fg=typer.colors.GREEN, bold=True)
            if lane.ok
            else typer.style("[FAIL]", fg=typer.colors.RED, bold=True)
        )
        typer.echo(
            f"{tag} {ui.text(lane.name, bold=True)}  {report.primary_label}: {lane.wrote}"
        )
        if lane.saw:
            typer.echo(f"       {ui.muted(lane.saw)}")

    if report.notes:
        ui.section("Notes")
        for note in report.notes:
            typer.echo(ui.muted(note))
    if report.lane_errors:
        ui.section("Fan-out lane errors")
        for error in report.lane_errors:
            ui.error(str(error))


@app.command()
def init(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    no_chmod: Annotated[
        bool,
        typer.Option(
            "--no-chmod",
            help="Skip chmod 0600 on databases (testing / cross-platform).",
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the report as JSON."),
    ] = False,
    all_lanes: Annotated[
        bool,
        typer.Option(
            "--all/--no-all",
            help="Initialize all six lanes with local defaults.",
        ),
    ] = False,
) -> None:
    """Create (reserve) every configured database, empty and ready.

    Per the runtime data plan §4.6: database files are chmod 0600 and the
    parent directories 0700, so a leaked snapshot cannot be read by a
    different user.

    This is the ``init`` verb of the Docker stack. It creates the five SQLite
    schemas, the JSONL and blob directories, and - when those lanes are
    configured as services - the three Milvus collections at the production
    embedding width and the Neo4j constraints. It writes no business data, and
    every step is idempotent (``IF NOT EXISTS`` at each layer).

    Lanes whose DSN names an in-process backend (``memory`` / ``none``) have
    nothing to create, so they are reported as skipped rather than counted as
    created. Exit codes: 0 everything configured was created; 1 a configured
    lane failed.
    """
    from Sprout.config.loader import load_settings
    from Sprout.storage.lanediag import STATUS_OK, init_lanes

    settings = load_settings(config)
    # ``ui.muted`` returns a styled string; it does not print. Every one of
    # these was a bare statement, so the whole ``[1/4]``…``[4/4]`` progress
    # narration the plan calls for was discarded in silence. In JSON mode it
    # stays off stdout on purpose (the payload has to be the only thing there).
    note = _progress_note_for(as_json=as_json)
    if all_lanes:
        note("[1/4] Configuring six-lane DSNs...")
        if settings.storage.cache in {"memory", "none"}:
            settings.storage.cache = "redis://127.0.0.1:6379/0"
        if settings.storage.vectors in {"memory", "none"}:
            settings.storage.vectors = "milvus://127.0.0.1:19530"
        if settings.storage.graph == "none":
            settings.storage.graph = "neo4j://neo4j:sprout123@127.0.0.1:7687"
        if settings.storage.context == "none":
            settings.storage.context = (
                "jsonl://"
                + (Path.home() / ".sprout" / "data" / "context").as_posix()
            )
        note("[2/4] Ensuring Python lane clients...")
        _ensure_lane_dependencies()
        note("[3/4] Pulling and starting Docker lanes...")
        _ensure_docker_lanes()
        _persist_lane_dsns(settings, config)
    note(
        f"Lanes: sqlite / jsonl / blob / redis={settings.storage.cache} / "
        f"milvus={settings.storage.vectors} / neo4j={settings.storage.graph}"
    )
    note("[4/4] Initializing and verifying all storage lanes...")
    report = asyncio.run(init_lanes(settings, progress=_lane_progress_for(as_json=as_json)))

    # Memory home is a filesystem layer (Hermes §MEMORY.md / USER.md).
    if settings.memory.enabled:
        from Sprout.memory.backends.file_system import FileSystemMemoryStore

        FileSystemMemoryStore(settings.memory.home)

    # Trajectory directory is reserved by JsonlTrajectoryRecorder at write
    # time, but `init` should leave a directory the daemon can stream into.
    Path(settings.storage.trajectory_dir).mkdir(parents=True, exist_ok=True)

    if not no_chmod:
        _apply_secure_permissions(settings)

    if as_json:
        typer.echo(json.dumps(_lanes_payload(report), indent=2, ensure_ascii=False))
        raise typer.Exit(report.status)

    ui.banner("SEAM_Sprout Storage", subtitle="Local stores reserved")
    ui.section("Runtime stores")
    typer.echo(ui.key_value("core", settings.storage.core))
    typer.echo(ui.key_value("conversation", settings.storage.conversation))
    typer.echo(ui.key_value("knowledge", settings.storage.knowledge))
    typer.echo(ui.key_value("audit", settings.storage.audit))
    if settings.storage.observations.enabled:
        typer.echo(ui.key_value("audit events", settings.storage.observations.dsn))
    typer.echo(ui.key_value("usage", settings.storage.usage))
    typer.echo(ui.key_value("projects", settings.storage.project_root))
    typer.echo(ui.key_value("blobs", f"{settings.storage.blobs_dir}/"))
    if settings.memory.enabled:
        ui.section("Memory layer (filesystem)")
        typer.echo(ui.key_value("home", settings.memory.home))
        typer.echo(ui.key_value("session cap", str(settings.memory.session_char_limit)))
        typer.echo(ui.key_value("user cap", str(settings.memory.user_char_limit)))
    ui.section("Trajectory")
    typer.echo(ui.key_value("dir", settings.storage.trajectory_dir))

    _render_lanes(report)
    if report.status == STATUS_OK:
        ui.success("Storage reserved.")
    else:
        ui.error(f"Storage initialisation failed (status {report.status}).")
    raise typer.Exit(report.status)


@app.command()
def check(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the report as JSON."),
    ] = False,
    all_lanes: Annotated[
        bool,
        typer.Option("--all", help="Check all six lanes with local defaults."),
    ] = False,
) -> None:
    """Prove every storage lane by writing once and reading each one back.

    The write goes through ``create_storage``, the way the runtime wires it; the
    verification deliberately does *not* reuse the contract objects — each lane is
    read with its own native client (sqlite3 on the file, Redis, Milvus, Neo4j,
    the blob directory, the JSONL log). That is the only way to catch a lane that
    silently swallowed the write, because the fan-out logs a lane failure instead
    of raising it.

    Lanes whose DSN names an in-process backend (``memory`` / ``none``) have no
    native client to read back with, so they are skipped and reported as skipped
    rather than counted as verified.

    Exit codes: 0 every checked lane holds the data; 1 a lane failed; 2 no
    six-lane fan-out is configured; 3 a stale Milvus collection has the wrong
    embedding width.
    """
    from Sprout.config.loader import load_settings
    from Sprout.storage.lanediag import STATUS_NO_FANOUT, STATUS_OK, check_lanes

    settings = load_settings(config)
    if all_lanes:
        if settings.storage.cache in {"memory", "none"}:
            settings.storage.cache = "redis://127.0.0.1:6379/0"
        if settings.storage.vectors in {"memory", "none"}:
            settings.storage.vectors = "milvus://127.0.0.1:19530"
        if settings.storage.graph == "none":
            settings.storage.graph = "neo4j://neo4j:sprout123@127.0.0.1:7687"
        if settings.storage.context == "none":
            settings.storage.context = (
                "jsonl://"
                + (Path.home() / ".sprout" / "data" / "context").as_posix()
            )
        _ensure_docker_lanes()
    report = asyncio.run(check_lanes(settings, progress=_lane_progress_for(as_json=as_json)))

    if as_json:
        typer.echo(json.dumps(_lanes_payload(report), indent=2, ensure_ascii=False))
        raise typer.Exit(report.status)

    ui.banner("SEAM_Sprout Storage", subtitle="Six-lane check")
    ui.section("Configuration")
    typer.echo(ui.key_value("config", config or "<default>"))
    for key, value in report.context:
        typer.echo(ui.key_value(key, value))

    _render_lanes(report)

    if report.status == STATUS_OK:
        if report.skipped:
            ui.success(
                f"{len(report.lanes)} lane(s) hold the data; "
                f"{len(report.skipped)} not service-backed and not verified."
            )
        else:
            ui.success("All six lanes hold the data.")
    elif report.status == STATUS_NO_FANOUT:
        # Exit 2 means "this configuration has nothing to prove", not "broken":
        # a laptop profile without derived lanes is a legitimate configuration.
        ui.warning("Nothing to prove - no six-lane fan-out is configured (status 2).")
    else:
        ui.error(f"Six-lane check failed (status {report.status}).")
    raise typer.Exit(report.status)


def _ensure_docker_lanes() -> None:
    """Start Redis, Neo4j, and Milvus with Docker when all lanes are requested."""
    if shutil.which("docker") is None:
        ui.warning("Sprout lane runner was not found; external lanes may fail to initialize.")
        return
    compose_file = Path.home() / ".sprout" / "docker" / "docker-compose.yml"
    typer.echo(ui.muted("Pulling Sprout lane images (redis, neo4j, milvus)..."))
    try:
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "sprout",
                "-f",
                str(compose_file),
                "pull",
                "sprout-redis",
                "sprout-neo4j",
                "sprout-milvus",
            ],
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        ui.warning("Sprout image pull timed out; continuing with initialization.")
    typer.echo(ui.muted("Starting Sprout lanes (redis, neo4j, milvus)..."))
    try:
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "sprout",
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--wait",
                "sprout-redis",
                "sprout-neo4j",
                "sprout-milvus",
            ],
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        ui.warning("Sprout lane startup timed out; external lanes may not be ready.")


def _ensure_lane_dependencies() -> None:
    """Install missing Python clients for external lanes when uv is available."""
    from Sprout.storage.lane_deps import ensure_lane_clients

    ensure_lane_clients(notify=ui.muted)


def _persist_lane_dsns(settings, config: str | None) -> None:
    """Write the derived-lane DSNs back into the user config so they stick."""
    if config:
        path = Path(config)
    elif os.environ.get("SPROUT_CONFIG"):
        path = Path(os.environ["SPROUT_CONFIG"])
    else:
        path = Path.home() / ".sprout" / "sprout.toml"
    if not path.exists():
        return

    lane_keys = {"cache", "vectors", "graph", "context"}
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if line.split("=", 1)[0].strip() not in lane_keys
    ]
    insert_at = None
    for index, line in enumerate(kept):
        if line.strip() == "[storage]":
            insert_at = index + 1
            break
    if insert_at is None:
        kept.append("[storage]")
        insert_at = len(kept)
    block = [
        f'cache = "{settings.storage.cache}"',
        f'vectors = "{settings.storage.vectors}"',
        f'graph = "{settings.storage.graph}"',
        f'context = "{settings.storage.context}"',
    ]
    kept[insert_at:insert_at] = block
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    typer.echo(ui.muted(f"Persisted six-lane DSNs to {path}"))


def _apply_secure_permissions(settings) -> None:
    """Chmod 0700 dirs, 0600 files where sqlite stores live (POSIX only)."""
    import os

    if sys.platform == "win32":
        return  # Windows ACLs are handled separately
    db_dsn_paths: list[str] = []
    for dsn in (
        settings.storage.operational,
        settings.storage.knowledge,
        settings.storage.metadata,
        settings.storage.session,
        settings.storage.usage,
    ):
        if dsn.startswith("sqlite:///"):
            db_dsn_paths.append(dsn.removeprefix("sqlite:///"))
    if settings.storage.observations.enabled:
        dsn = settings.storage.observations.dsn
        if dsn.startswith("sqlite:///"):
            db_dsn_paths.append(dsn.removeprefix("sqlite:///"))
    for raw in db_dsn_paths:
        path = Path(raw)
        try:
            if path.exists():
                os.chmod(path, 0o600)
            parent = path.parent
            if parent.exists() and parent != Path("."):
                os.chmod(parent, 0o700)
        except OSError:
            pass  # best effort; backup dirs may be read-only
    media_dir = Path(settings.storage.blobs_dir)
    if media_dir.exists():
        try:
            os.chmod(media_dir, 0o700)
        except OSError:
            pass
    memory_home = Path(settings.memory.home)
    if settings.memory.enabled and memory_home.exists():
        try:
            os.chmod(memory_home, 0o700)
        except OSError:
            pass
    trajectory_dir = Path(settings.storage.trajectory_dir)
    if trajectory_dir.exists():
        try:
            os.chmod(trajectory_dir, 0o700)
        except OSError:
            pass


@app.command()
def status(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show row counts for every reserved store."""
    from Sprout.config.loader import load_settings
    from Sprout.storage.bundle import create_storage, storage_status

    settings = load_settings(config)
    bundle = create_storage(settings.storage, memory_settings=settings.memory)
    try:
        status = asyncio.run(storage_status(bundle))
    finally:
        asyncio.run(bundle.close())

    operational = status.pop("operational")
    session_layer = status.pop("session_layer", None)
    sqlite_info = status.pop("sqlite", None)
    memory_info = status.pop("memory", None)
    search_info = status.pop("session_search", None)
    ui.banner("SEAM_Sprout Storage", subtitle="Row counts by store")
    if sqlite_info is not None:
        ui.section("SQLite capabilities")
        typer.echo(ui.key_value("version", sqlite_info.get("sqlite_version", "?")))
        typer.echo(ui.key_value("fts5", str(sqlite_info.get("fts5", False))))
        typer.echo(ui.key_value("trigram", str(sqlite_info.get("trigram", False))))
        typer.echo(ui.key_value("wal", str(sqlite_info.get("wal", False))))
    ui.section("Runtime")
    typer.echo(ui.key_value("sessions", operational.get("sessions", 0)))
    typer.echo(ui.key_value("turns", operational.get("turns", 0)))
    typer.echo(ui.key_value("tasks", operational.get("tasks", 0)))
    typer.echo(ui.key_value("approvals", operational.get("approvals", 0)))
    if session_layer is not None:
        ui.section(f"Session layer ({session_layer['backend']})")
        typer.echo(ui.key_value("sessions", session_layer["sessions"]))
        typer.echo(ui.key_value("turns", session_layer["turns"]))
    if search_info is not None:
        ui.section(f"Session search ({search_info['backend']})")
        typer.echo(ui.key_value("tokenizer", search_info.get("tokenizer") or "?"))
    if memory_info is not None:
        ui.section(f"Memory layer ({memory_info['backend']})")
        typer.echo(ui.key_value("facts", memory_info.get("facts") or 0))
    ui.section("Other stores")
    typer.echo(ui.key_value("knowledge", status.get("knowledge", 0)))
    typer.echo(ui.key_value("events", status.get("events", 0)))
    typer.echo(ui.key_value("blobs", status.get("blobs", 0)))
    typer.echo(ui.key_value("vectors", status.get("vectors", 0)))


@app.command("health")
def health(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    all_lanes: Annotated[
        bool,
        typer.Option(
            "--all/--no-all",
            help="Check all six lanes with local defaults.",
        ),
    ] = False,
) -> None:
    """Print only the running/healthy status of every database lane."""
    from Sprout.config.loader import load_settings
    from Sprout.storage.lanediag import check_lanes

    settings = load_settings(config)
    if all_lanes:
        if settings.storage.cache in {"memory", "none"}:
            settings.storage.cache = "redis://127.0.0.1:6379/0"
        if settings.storage.vectors in {"memory", "none"}:
            settings.storage.vectors = "milvus://127.0.0.1:19530"
        if settings.storage.graph == "none":
            settings.storage.graph = "neo4j://neo4j:sprout123@127.0.0.1:7687"
        if settings.storage.context == "none":
            settings.storage.context = (
                "jsonl://"
                + (Path.home() / ".sprout" / "data" / "context").as_posix()
            )
    report = asyncio.run(check_lanes(settings))
    for lane in report.lanes:
        state = "healthy" if lane.ok else "failed"
        typer.echo(f"{state:<8} {lane.name}")
    for skipped in report.skipped:
        typer.echo(f"{'skipped':<8} {skipped}")


@app.command()
def backup(
    target: Annotated[
        str, typer.Argument(help="Destination directory for the backup.")
    ],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Online backup of every SQLite database (M13)."""
    from Sprout.config.loader import load_settings
    from Sprout.storage.bundle import create_storage
    from Sprout.storage.local.sqlite.driver import SqliteDatabase

    settings = load_settings(config)
    bundle = create_storage(settings.storage, memory_settings=settings.memory)
    target_dir = Path(target)
    target_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[str, object]] = []
    for name in ("operational", "knowledge", "metadata", "observations", "session"):
        candidate = getattr(bundle, name, None)
        if candidate is not None:
            db = getattr(candidate, "_db", None)
            if isinstance(db, SqliteDatabase):
                candidates.append((name, db))
    for name, db in candidates:
        out = target_dir / f"{name}.db"
        db.backup_to(out)
        typer.echo(f"  wrote {out}")
    asyncio.run(bundle.close())
    ui.success(f"Backup complete: {target_dir}")


@app.command()
def restore(
    source: Annotated[str, typer.Argument(help="Source backup directory.")],
    target: Annotated[
        str | None,
        typer.Option("--target", help="Where to write the restored files."),
    ] = None,
) -> None:
    """Restore a backup onto ``--target``.

    ``--target`` is required: restoring onto the backup directory itself would
    overwrite the very files being read, so there is no safe default.
    """
    import shutil

    from Sprout.storage.local.sqlite.driver import SqliteDatabase

    source_dir = Path(source)
    if not source_dir.is_dir():
        raise typer.BadParameter(f"Not a backup directory: {source_dir}")
    if target is None:
        raise typer.BadParameter(
            "--target is required: restoring onto the backup directory itself "
            "would overwrite the source files."
        )
    target_dir = Path(target)
    if target_dir.resolve() == source_dir.resolve():
        raise typer.BadParameter(
            "--target must differ from the backup directory, or the backup "
            "would overwrite itself."
        )

    backups = sorted(source_dir.glob("*.db"))
    if not backups:
        raise typer.BadParameter(f"No *.db backups found in {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    restored = []
    for file in backups:
        out = target_dir / file.name
        if out.exists():
            raise typer.BadParameter(
                f"Refusing to overwrite existing {out}; move it aside first."
            )
        # Copy the bytes first: opening the destination with SqliteDatabase.open
        # would create an empty database when the file is missing, and the
        # quick_check below would then report "ok" for that empty schema.
        shutil.copy2(file, out)
        db = SqliteDatabase.open(out)
        try:
            db.checkpoint("TRUNCATE")
            ok = db.quick_check()
        finally:
            db.close()
        restored.append(f"{file.name} ({'ok' if ok else 'FAILED'})")
    ui.success(f"Restored: {', '.join(restored)}")


@app.command()
def approvals(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """List approval requests for risky tool calls."""
    from Sprout.config.loader import load_settings
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    bundle = create_storage(settings.storage, memory_settings=settings.memory)

    async def _run() -> list:
        return list(await bundle.operational.list_approvals())

    try:
        records = asyncio.run(_run())
    finally:
        asyncio.run(bundle.close())

    ui.banner("Approval Requests", subtitle=f"{len(records)} record(s)")
    if not records:
        typer.echo(ui.muted("No approval records."))
        return
    for record in records:
        status_color = {
            "pending": typer.colors.YELLOW,
            "approved": typer.colors.GREEN,
            "rejected": typer.colors.RED,
        }.get(record.status.value, typer.colors.BRIGHT_WHITE)
        typer.echo(
            f"  {typer.style(f'[{record.status.value:>8}]', fg=status_color, bold=True)} "
            f"{record.tool} ({record.id[:8]})"
        )
        typer.echo(ui.muted(f"    requested_by={record.requested_by}"
                            f"{f'  decided_by={record.decided_by}' if record.decided_by else ''}"))


@app.command()
def plan(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the data-layer plan as JSON."),
    ] = False,
) -> None:
    """Show which database owns what, and how it is called."""
    from Sprout.config.loader import load_settings
    from Sprout.storage.plan import data_layer_plan
    from Sprout.storage.topology import topology_plan

    settings = load_settings(config)
    entries = data_layer_plan(settings.storage)
    topo = topology_plan()
    if as_json:
        out = {"lanes": entries, "topology": topo}
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    ui.banner("SEAM_Sprout Data Layer", subtitle="One authority per entity")
    for entry in entries:
        lane = "authority" if entry["authority"] else "derived"
        ui.section(f"{entry['key']}  [{lane}] {entry['scheme']}")
        typer.echo(ui.key_value("dsn", entry["dsn"]))
        typer.echo(ui.key_value("responsibility", entry["responsibility"]))
        typer.echo(ui.key_value("contract", entry["contract"]))
        typer.echo(ui.key_value("backend", entry["backend"]))
        typer.echo(ui.key_value("retention", entry["retention"]))
        for name in entry["owns"]:
            typer.echo(ui.bullet(name, ""))
    typer.echo(ui.muted("Callers use contracts only; the DSN picks the backend."))

    ui.section("Entity ownership (topology registry)")
    for own in topo["entities"]:
        derived = ", ".join(own["derived"]) if own["derived"] else "-"
        typer.echo(ui.key_value(own["entity"], f"{own['authority']} ← {own['authority_backend']}"))
        if own["payload_lane"]:
            typer.echo(ui.bullet(f"payload → {own['payload_lane']}", ""))
        if own["derived"]:
            typer.echo(ui.bullet(f"derived: {derived}", ""))

    ui.section("On-disk databases (8 → 6 consolidation)")
    for db in topo["databases"]:
        status_color = {
            "active": typer.colors.GREEN,
            "rehome": typer.colors.YELLOW,
            "legacy": typer.colors.RED,
        }.get(db["status"], typer.colors.BRIGHT_WHITE)
        typer.echo(
            ui.key_value(
                db["filename"],
                typer.style(
                    f"[{db['status']}] {db['owns']} → {db['action']}",
                    fg=status_color,
                ),
            )
        )


@app.command()
def migrate(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Move rows and archive drained sources. Default is a dry run.",
        ),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the migration report as JSON.")
    ] = False,
) -> None:
    """Carry out the rehome dispositions declared in the storage topology."""
    del config  # disposition is derived from topology, not runtime settings
    from Sprout.storage.migrate import run_migration

    report = run_migration(apply=apply)
    if as_json:
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
        return

    ui.banner(
        "SEAM_Sprout Storage Migration",
        subtitle="apply --apply to execute" if not apply else "applying changes",
    )
    if not report["entries"]:
        ui.section("Nothing to migrate")
        typer.echo(ui.muted("Every declared database is already in its target authority."))
        return

    for entry in report["entries"]:
        target = f" → {entry['target']}" if entry["target"] else ""
        ui.section(f"{entry['source']}{target}  [{entry['status']}]")
        for line in entry["details"]:
            typer.echo(ui.bullet(line, ""))
    if report.get("backup"):
        typer.echo(ui.muted(f"backup: {report['backup']}"))
    elif not apply:
        typer.echo(ui.muted("Dry run — nothing was written. Re-run with --apply to execute."))

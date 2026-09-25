"""Bring configured storage services up and initialise their schemas."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from Sprout.storage.lane_deps import (
    ensure_lane_clients,
    missing_lane_clients,
    required_lane_clients,
)
from Sprout.storage.lanediag import LaneReport, init_lanes

_INITIALIZED: set[tuple[str, ...]] = set()
_SERVICE_NAMES = {
    "redis": "sprout-redis",
    "milvus": "sprout-milvus",
    "neo4j": "sprout-neo4j",
}


def _storage_key(settings) -> tuple[str, ...]:
    storage = settings.storage
    return (
        storage.operational,
        storage.knowledge,
        storage.metadata or "",
        storage.observations.dsn if storage.observations.enabled else "disabled",
        storage.session,
        storage.cache,
        storage.vectors,
        storage.graph,
        storage.context,
        storage.usage,
        storage.blobs_dir,
        str(settings.memory.enabled),
        settings.memory.home,
    )


def _local_dsns(settings) -> dict[str, str]:
    """Configured external lanes whose DSN points at this machine."""
    storage = settings.storage
    dsns = {"redis": storage.cache, "milvus": storage.vectors, "neo4j": storage.graph}
    local: dict[str, str] = {}
    for kind, dsn in dsns.items():
        if not dsn.startswith(f"{kind}://"):
            continue
        if urlsplit(dsn).hostname in {"127.0.0.1", "localhost", "::1"}:
            local[kind] = dsn
    return local


def _local_services(settings) -> list[str]:
    """Return compose services for configured external lanes on this machine."""
    return [_SERVICE_NAMES[kind] for kind in _local_dsns(settings)]


def _port_is_open(dsn: str, *, timeout: float = 0.5) -> bool:
    """Is something already accepting connections at this DSN's host and port?

    A TCP connect is enough to answer this: every lane here speaks a protocol
    that only starts after the listener is up, and the alternative — a
    protocol-level handshake per lane — would mean importing the optional lane
    clients before we know whether they are even needed.
    """
    parsed = urlsplit(dsn)
    if not parsed.hostname or parsed.port is None:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def _await_listening(dsn: str, *, timeout: float = 60.0) -> None:
    """Block until ``dsn``'s port answers, or give up quietly.

    Called after adopting a stopped container. Giving up silently rather than
    raising is deliberate: the lane initialisers report an unreachable service
    with far better context than "port never opened", and a slow Neo4j must not
    fail startup on its own.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(dsn):
            return
        time.sleep(0.5)


def _services_needing_start(settings) -> list[str]:
    """The local services that are *not* already answering on their port.

    Bringing up an already-running stack is what made ``sprout chat`` fail on a
    machine whose containers were healthy: the generated compose file pins
    ``container_name`` while the bootstrap passes a fixed ``--project-name``, so
    compose tried to create ``/sprout-neo4j`` a second time and exited non-zero
    on the name conflict. The containers belonged to a project with a different
    name, so nothing was wrong with them — the ``up`` was simply unnecessary.

    Probing first makes that case a no-op instead of a hard failure, and
    ``up`` still runs for whatever is genuinely down, which is what a cold
    machine needs.
    """
    local = _local_dsns(settings)
    return [
        _SERVICE_NAMES[kind]
        for kind, dsn in local.items()
        if not _port_is_open(dsn)
    ]


def _start_existing_container(docker: str, name: str) -> bool:
    """Start a container that already exists but is stopped.

    A stopped container still owns its volumes, and those may be *anonymous*
    ones the current compose file knows nothing about — a stack brought up by an
    earlier revision keeps its redis keys and neo4j graph there rather than in
    the named volumes this file declares. Letting ``up`` create a parallel
    container would leave that data attached to an orphan, so a container we
    find is adopted instead of duplicated.

    Returns whether a container by that name was started. ``False`` means there
    is nothing to adopt, and the caller should let compose create one.
    """
    try:
        completed = subprocess.run(
            [docker, "start", name],
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


async def _start_local_services(settings) -> None:
    if os.environ.get("SPROUT_STORAGE_AUTO_START", "true").lower() in {
        "0",
        "false",
        "no",
    }:
        return
    services = await asyncio.to_thread(_services_needing_start, settings)
    if not services:
        return
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(
            "Configured local storage lanes require Docker, but docker was not found. "
            "Install/start Docker or set SPROUT_STORAGE_AUTO_START=false."
        )

    # Adopt before create: a stopped container already holds the data.
    local = _local_dsns(settings)
    by_service = {_SERVICE_NAMES[kind]: dsn for kind, dsn in local.items()}
    adopted: set[str] = set()
    for name in services:
        if await asyncio.to_thread(_start_existing_container, docker, name):
            adopted.add(name)
    services = [name for name in services if name not in adopted]
    if services:
        # Compose's ``--wait`` covers the ones it creates, but a container we
        # started ourselves gets no such healthcheck — and ``init_lanes`` would
        # race a redis that is listening but not yet answering.
        for name in sorted(adopted):
            dsn = by_service.get(name)
            if dsn is not None:
                await asyncio.to_thread(_await_listening, dsn)
    if not services:
        return
    compose_file = Path.home() / ".sprout" / "docker" / "docker-compose.yml"
    command = [
        docker,
        "compose",
        "--project-name",
        "sprout",
        "-f",
        str(compose_file),
        "up",
        "-d",
        "--wait",
        *services,
    ]

    def run() -> None:
        completed = subprocess.run(
            command,
            check=False,
            timeout=300,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if completed.returncode != 0:
            # Compose prints the actionable cause (engine down, port clash,
            # image pull failure) last, so keep the tail instead of discarding
            # it and reporting a bare exit code.
            detail = (completed.stderr or completed.stdout or "").strip()
            tail = "\n".join(detail.splitlines()[-15:])
            raise RuntimeError(
                f"Docker storage startup failed (exit {completed.returncode}): "
                f"{', '.join(services)}" + (f"\n{tail}" if tail else "")
            )

    await asyncio.to_thread(run)


async def _ensure_lane_clients(settings) -> None:
    """Install the Python clients for the configured external lanes.

    The lane clients live in the optional ``lanes`` extra, so a runtime started
    from a plain ``uv run`` may not have them. Reporting the missing package
    here beats failing later inside lane assembly with an opaque message.
    """
    required = required_lane_clients(settings.storage)
    if not required:
        return
    await asyncio.to_thread(ensure_lane_clients, required)
    still_missing = missing_lane_clients(required)
    if still_missing:
        raise RuntimeError(
            "Configured storage lanes need Python clients that are not "
            f"installed: {', '.join(still_missing)}. "
            "Run `uv sync --extra lanes` to install them."
        )


async def ensure_storage_ready(settings) -> LaneReport:
    """Start configured service lanes and initialise every configured store.

    The operation is process-idempotent and the underlying lane initialisers
    are database-idempotent, so repeated Runtime/transport starts are cheap.
    """
    key = _storage_key(settings)
    if key in _INITIALIZED:
        return LaneReport(title="STORAGE READY", primary_label="detail")

    await _ensure_lane_clients(settings)
    await _start_local_services(settings)
    report = await init_lanes(settings)
    if report.status != 0 or report.lane_errors:
        details = "; ".join(report.lane_errors) or f"status={report.status}"
        raise RuntimeError(f"Storage initialisation failed: {details}")
    _INITIALIZED.add(key)
    return report


def ensure_storage_sync(settings) -> LaneReport:
    """Synchronous bridge for CLI and direct server entry points."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(ensure_storage_ready(settings))
    raise RuntimeError("ensure_storage_sync() cannot run inside an active event loop")

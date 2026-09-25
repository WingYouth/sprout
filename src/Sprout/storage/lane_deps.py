"""Ensure the Python clients for the external storage lanes are importable.

Redis, Milvus, and Neo4j ship as the optional ``lanes`` extra, so a plain
``uv sync`` / ``uv run`` leaves them out. A runtime pointed at those lanes then
fails deep inside lane assembly with an opaque "assembly failed" message.
Checking the clients up front turns that into an actionable step: install them,
or report exactly which one is missing.

``sprout storage init/check --all`` and the runtime
(:func:`Sprout.storage.bootstrap.ensure_storage_ready`) both go through here so
"which packages, installed how" is defined once.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable

# Import name -> requirement specifier, keyed by the lane it serves.
LANE_CLIENTS: dict[str, str] = {
    "redis": "redis>=5.0",
    "pymilvus": "pymilvus>=2.4",
    "neo4j": "neo4j>=5.20",
}


def required_lane_clients(storage) -> list[str]:
    """Return the lane client modules implied by the configured DSN schemes."""
    needed: list[str] = []
    if str(storage.cache).startswith("redis://"):
        needed.append("redis")
    if str(storage.vectors).startswith("milvus://"):
        needed.append("pymilvus")
    if str(storage.graph).startswith("neo4j://"):
        needed.append("neo4j")
    return needed


def missing_lane_clients(required: Iterable[str] | None = None) -> list[str]:
    """Return lane clients that cannot be imported.

    ``required=None`` checks every known lane client; pass an explicit list to
    check only the lanes a given configuration actually uses.
    """
    packages = list(required) if required is not None else list(LANE_CLIENTS)
    return [name for name in packages if importlib.util.find_spec(name) is None]


def ensure_lane_clients(
    required: Iterable[str] | None = None,
    *,
    notify: Callable[[str], None] | None = None,
) -> list[str]:
    """Best-effort install of the missing lane clients via ``uv``.

    Returns the names that were missing, so callers can re-check whether the
    install actually took. ``notify`` receives human-readable progress; omit it
    to stay silent.
    """

    def _say(message: str) -> None:
        if notify is not None:
            notify(message)

    missing = missing_lane_clients(required)
    if not missing:
        return []

    uv = shutil.which("uv")
    if uv is None:
        _say(
            "Missing lane clients "
            f"({', '.join(missing)}) and uv was not found; "
            "run `uv sync --extra lanes` to install them."
        )
        return missing

    _say(f"Installing missing lane clients: {', '.join(missing)}...")
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            *(LANE_CLIENTS[name] for name in missing),
        ],
        check=False,
    )
    return missing

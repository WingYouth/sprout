"""Rootstock (砧木): the session persistence layer of SEAM_Sprout.

A sprout is grafted onto a rootstock — the root system that stores and feeds
it. This package is that root system for the session layer: one
:class:`~Sprout.rootstock.contract.SessionStore` protocol, six backend slots
(SQLite, JSONL, blobstore, Milvus, Neo4j, Redis) plus an in-memory fallback,
all selected by a single DSN in ``[storage] session``.

Usage::

    from Sprout.rootstock import create_session_store

    store = create_session_store("sqlite:////<home>/.sprout/data/sprout_conversation.db")
    await store.save_session(session)
    await store.append_turn(turn)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from Sprout.rootstock.contract import SessionStore
from Sprout.rootstock.errors import RootstockUnavailableError

if TYPE_CHECKING:
    from Sprout.rootstock.backends import (
        BACKENDS,
        BlobSessionStore,
        JsonlSessionStore,
        MemorySessionStore,
        MilvusSessionStore,
        Neo4jSessionStore,
        RedisSessionStore,
        SqliteSessionStore,
        create_session_store,
    )

__all__ = [
    "BACKENDS",
    "BlobSessionStore",
    "JsonlSessionStore",
    "MemorySessionStore",
    "MilvusSessionStore",
    "Neo4jSessionStore",
    "RedisSessionStore",
    "RootstockUnavailableError",
    "SessionStore",
    "SqliteSessionStore",
    "create_session_store",
]

# Backends import ``Sprout.storage`` (SQLite driver, blob store) while
# ``Sprout.storage.bundle`` imports this package, so they are resolved on first
# attribute access instead of at import time. Without this the two packages
# deadlock each other during module initialisation.
_BACKEND_ATTRIBUTES = frozenset(
    {
        "BACKENDS",
        "BlobSessionStore",
        "JsonlSessionStore",
        "MemorySessionStore",
        "MilvusSessionStore",
        "Neo4jSessionStore",
        "RedisSessionStore",
        "SqliteSessionStore",
        "create_session_store",
    }
)


def __getattr__(name: str) -> Any:
    if name in _BACKEND_ATTRIBUTES:
        from Sprout.rootstock import backends

        return getattr(backends, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)

"""Rootstock backends: one DSN-dispatched factory, six backend slots.

Supported session DSN schemes:

- ``sqlite:////<home>/.sprout/data/sprout_conversation.db`` — SQLite (default, fully implemented)
- ``jsonl:///<home>/.sprout/data/session.jsonl`` — append-only JSONL (fully implemented)
- ``blobstore:///<home>/.sprout/data/session-blobs`` — JSON documents in a blob store (implemented)
- ``milvus://host:19530`` — vector backend (implemented; also takes
  ``milvus:///path/to.db`` for embedded Milvus Lite)
- ``neo4j://host:7687`` — graph backend (implemented)
- ``redis://host:6379`` — hot-cache backend (implemented)
- ``memory://`` — in-memory fallback for tests and ephemeral runtimes
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Sprout.rootstock.backends.blob_store import BlobSessionStore
from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
from Sprout.rootstock.backends.memory_store import MemorySessionStore
from Sprout.rootstock.backends.milvus_store import MilvusSessionStore
from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore
from Sprout.rootstock.backends.redis_store import RedisSessionStore
from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.rootstock.contract import SessionStore

if TYPE_CHECKING:
    from Sprout.storage.local.sqlite.driver import SqlitePragmas

__all__ = [
    "BACKENDS",
    "BlobSessionStore",
    "JsonlSessionStore",
    "MemorySessionStore",
    "MilvusSessionStore",
    "Neo4jSessionStore",
    "RedisSessionStore",
    "SqliteSessionStore",
    "create_session_store",
]


def _split_dsn(dsn: str) -> tuple[str, str | None]:
    """Split ``sqlite:////<home>/.sprout/data/sprout_conversation.db`` into scheme/path."""
    scheme, _, rest = dsn.partition("://")
    if not scheme:
        raise ValueError(f"Invalid session DSN: {dsn!r}")
    if scheme == "memory":
        return "memory", None
    return scheme, rest.removeprefix("/") or None


def create_session_store(
    dsn: str, pragmas: SqlitePragmas | None = None
) -> SessionStore:
    """Assemble the session store named by a DSN.

    Local schemes (``sqlite``, ``jsonl``, ``blobstore``) reserve their files on
    open; the external schemes (``milvus``, ``neo4j``, ``redis``) validate the
    client package eagerly so a missing dependency fails at assembly, not at
    the first turn (the servers themselves are reached lazily on first use).
    ``pragmas`` tunes the SQLite backend only.
    """
    scheme, rest = _split_dsn(dsn)
    if scheme == "memory":
        return MemorySessionStore()
    if scheme == "sqlite":
        if not rest:
            raise ValueError(f"SQLite session DSN needs a file path: {dsn!r}")
        from Sprout.rootstock.backends.sqlite_store import open_session_store

        return open_session_store(rest, pragmas)
    if scheme == "jsonl":
        if not rest:
            raise ValueError(f"JSONL session DSN needs a file path: {dsn!r}")
        return JsonlSessionStore(rest)
    if scheme == "blobstore":
        if not rest:
            raise ValueError(f"Blobstore session DSN needs a directory: {dsn!r}")
        # Imported here: the blob contract lives in the storage layer, and
        # importing it at module scope would make rootstock and storage
        # import each other in a cycle.
        from Sprout.storage.local.filesystem.blobs import FileBlobStore

        return BlobSessionStore(rest, FileBlobStore(f"{rest}/blobs"))
    if scheme == "milvus":
        return MilvusSessionStore(dsn)
    if scheme == "neo4j":
        return Neo4jSessionStore(dsn)
    if scheme == "redis":
        return RedisSessionStore(dsn)
    raise ValueError(f"Unsupported session DSN: {dsn!r}")


#: Backend slots addressable by scheme, for inspection and tooling.
BACKENDS: dict[str, str] = {
    "memory": "MemorySessionStore",
    "sqlite": "SqliteSessionStore",
    "jsonl": "JsonlSessionStore",
    "blobstore": "BlobSessionStore",
    "milvus": "MilvusSessionStore",
    "neo4j": "Neo4jSessionStore",
    "redis": "RedisSessionStore",
}

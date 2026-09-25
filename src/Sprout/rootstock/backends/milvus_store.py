"""Milvus session backend: the vector lane behind the SessionStore protocol.

Turns live in one collection with their embeddings so semantic session recall
can replace keyset paging when a Milvus deployment is available; sessions
live in a scalar-only companion collection. Requires the ``pymilvus`` client
and a reachable Milvus instance (``milvus://host:19530``).

The client connects and the schema is created lazily on first use, so
constructing the store against a down server fails on the first operation,
not at assembly — matching the fail-late behavior of the SQLite backend's
read paths and keeping ``create_session_store`` cheap.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from datetime import UTC, datetime
from typing import Any

from Sprout.rootstock.contract import blob_uris_in
from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.session.models import Session, Turn
from Sprout.storage.embeddings import Embedder, HashingEmbedder

COLLECTION = "sprout_vec_messages"
SESSIONS_COLLECTION = "sprout_sessions"
EMBEDDING_DIM = 1536

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")


def normalize_uri(dsn: str) -> str:
    """``milvus://host:19530`` -> ``http://host:19530`` (remote server);
    ``milvus:///path/to.db`` -> the bare path (embedded Milvus Lite)."""
    rest = dsn.removeprefix("milvus://") if dsn.startswith("milvus://") else dsn
    if not rest:
        return dsn
    if _WINDOWS_DRIVE.match(rest):
        return rest
    if rest.startswith("/"):
        return rest.lstrip("/")
    return rest if "://" in rest else f"http://{rest}"

#: Declarative storage contract: what the adapter declares to the schema
#: manager. ``turn_id`` is the primary key (VARCHAR — turn ids are uuid4).
FIELDS: dict[str, dict[str, object]] = {
    "embedding": {"type": "FLOAT_VECTOR", "dim": EMBEDDING_DIM},
    "turn_id": {"type": "VARCHAR", "max_length": 64, "is_primary": True},
    "session_id": {"type": "VARCHAR", "max_length": 64},
    "seq": {"type": "INT64"},
    "role": {"type": "VARCHAR", "max_length": 16},
    "text": {"type": "VARCHAR", "max_length": 65535},
    "metadata_json": {"type": "VARCHAR", "max_length": 65535},
}


def _require_pymilvus(dsn: str) -> None:
    if importlib.util.find_spec("pymilvus") is None:
        raise RootstockUnavailableError(
            "The milvus session backend requires the 'pymilvus' package. "
            f"Install it (e.g. `uv add pymilvus`) and set [storage] session = "
            f'"{dsn}".'
        )


class MilvusSessionStore:
    """Sessions and embedded turns in two Milvus collections."""

    backend_name = "milvus"

    def __init__(
        self, dsn: str, *, embed: Embedder | None = None, dim: int = EMBEDDING_DIM
    ) -> None:
        _require_pymilvus(dsn)
        self.dsn = dsn
        self.dim = dim
        self._embed = embed or HashingEmbedder(dim)
        self._client: Any = None
        self._ready = False
        self._seq_cache: dict[str, int] = {}
        # Whether the turns collection carries the ``metadata_json`` envelope
        # column; False on collections created before the envelope existed,
        # in which case turns are stored without their envelope (graceful
        # degradation — the envelope survives in the authority lane).
        self._turn_envelope_supported = False

    def _ensure_client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=normalize_uri(self.dsn))
        return self._client

    def _ensure_schema(self) -> None:
        """Create both collections, load them (idempotent).

        Milvus (embedded Lite and standalone alike) serves ``search``/``query``
        only from *loaded* collections; loading on open (and re-loading after
        a server restart) is part of the adapter's job.
        """
        if self._ready:
            return
        client = self._ensure_client()
        from pymilvus import DataType

        if not client.has_collection(SESSIONS_COLLECTION):
            # Milvus requires a vector field on every collection; sessions are
            # scalar-only rows, so they carry a zero vector and are never
            # searched by similarity.
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(
                "turn_id", DataType.VARCHAR, is_primary=True, max_length=64
            )
            schema.add_field("user_id", DataType.VARCHAR, max_length=128)
            schema.add_field("created_at", DataType.VARCHAR, max_length=64)
            schema.add_field("metadata_json", DataType.VARCHAR, max_length=65535)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding", index_type="FLAT", metric_type="COSINE"
            )
            client.create_collection(
                SESSIONS_COLLECTION, schema=schema, index_params=index_params
            )

        if not client.has_collection(COLLECTION):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(
                "turn_id", DataType.VARCHAR, is_primary=True, max_length=64
            )
            schema.add_field("session_id", DataType.VARCHAR, max_length=64)
            schema.add_field("seq", DataType.INT64)
            schema.add_field("role", DataType.VARCHAR, max_length=16)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("metadata_json", DataType.VARCHAR, max_length=65535)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding", index_type="FLAT", metric_type="COSINE"
            )
            client.create_collection(
                COLLECTION, schema=schema, index_params=index_params
            )
        try:
            described = client.describe_collection(COLLECTION)
            field_names = {
                field.get("name") for field in described.get("fields", [])
            }
            self._turn_envelope_supported = "metadata_json" in field_names
        except Exception:  # noqa: BLE001 - degrade to no-envelope on old servers
            self._turn_envelope_supported = False
        client.load_collection(SESSIONS_COLLECTION)
        client.load_collection(COLLECTION)
        self._ready = True

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
            self._ready = False

    # -- helpers -------------------------------------------------------------

    async def _query(self, collection: str, filt: str, output: list[str]) -> list[dict]:
        def _run() -> list[dict]:
            self._ensure_schema()
            return list(
                self._ensure_client().query(
                    collection, filter=filt, output_fields=output
                )
            )

        return await asyncio.to_thread(_run)

    async def _query_turns(self, filt: str) -> list[dict]:
        """Query turn rows, including the envelope column when it exists.

        The field list is computed *after* ``_ensure_schema`` has run (inside
        the worker thread), so the very first query already knows whether the
        collection carries ``metadata_json``.
        """

        def _run() -> list[dict]:
            self._ensure_schema()
            fields = ["turn_id", "session_id", "seq", "role", "text"]
            if self._turn_envelope_supported:
                fields.append("metadata_json")
            return list(
                self._ensure_client().query(
                    COLLECTION, filter=filt, output_fields=fields
                )
            )

        return await asyncio.to_thread(_run)

    async def _next_seq(self, session_id: str) -> int:
        if session_id in self._seq_cache:
            self._seq_cache[session_id] += 1
            return self._seq_cache[session_id]
        rows = await self._query(COLLECTION, f'session_id == "{session_id}"', ["seq"])
        highest = max((int(row["seq"]) for row in rows), default=0)
        self._seq_cache[session_id] = highest + 1
        return highest + 1

    @staticmethod
    def _row_to_turn(row: dict) -> Turn:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return Turn(
            session_id=row["session_id"],
            role=row["role"],
            content=row["text"],
            id=row["turn_id"],
            created_at=datetime.now(UTC),
            seq=int(row["seq"]),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    # -- SessionStore protocol -----------------------------------------------

    async def get_session(self, session_id: str) -> Session | None:
        rows = await self._query(
            SESSIONS_COLLECTION,
            f'turn_id == "{session_id}"',
            ["user_id", "created_at", "metadata_json"],
        )
        if not rows:
            return None
        row = rows[0]
        return Session(
            id=session_id,
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row.get("metadata_json") or "{}"),
        )

    async def save_session(self, session: Session) -> None:
        def _run() -> None:
            self._ensure_schema()
            client = self._ensure_client()
            client.upsert(
                SESSIONS_COLLECTION,
                [
                    {
                        "turn_id": session.id,
                        "user_id": session.user_id,
                        "created_at": session.created_at.isoformat(),
                        "metadata_json": json.dumps(
                            session.metadata, ensure_ascii=False, default=str
                        ),
                        "embedding": [0.0] * self.dim,
                    }
                ],
            )
            # Standalone Milvus serves queries at bounded consistency; flush
            # makes the write visible to an immediate read-back.
            client.flush(SESSIONS_COLLECTION)

        await asyncio.to_thread(_run)

    async def append_turn(self, turn: Turn) -> None:
        # ``turn.seq`` is honored when nonzero: the six-lane fan-out passes the
        # authority-assigned sequence so the vector lane mirrors it exactly.
        if turn.seq > 0:
            seq = turn.seq
            self._seq_cache[turn.session_id] = seq
        else:
            seq = await self._next_seq(turn.session_id)
        row: dict[str, Any] = {
            "turn_id": turn.id,
            "session_id": turn.session_id,
            "seq": seq,
            "role": turn.role,
            "text": turn.content,
            "embedding": self._embed(turn.content),
        }
        if self._turn_envelope_supported:
            row["metadata_json"] = json.dumps(
                turn.metadata or {}, ensure_ascii=False, default=str
            )

        def _run() -> None:
            self._ensure_schema()
            client = self._ensure_client()
            client.upsert(COLLECTION, [row])
            client.flush(COLLECTION)

        await asyncio.to_thread(_run)

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        rows = await self._query_turns(f'session_id == "{session_id}"')
        rows.sort(key=lambda row: int(row["seq"]), reverse=True)
        turns = [self._row_to_turn(row) for row in rows[:limit]]
        turns.reverse()
        return turns

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> list[Turn]:
        rows = await self._query_turns(
            f'session_id == "{session_id}" and seq < {int(seq)}'
        )
        rows.sort(key=lambda row: int(row["seq"]))
        return [self._row_to_turn(row) for row in rows[:limit]]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(await self.turns_before(session_id, seq=10**12, limit=10**6))

    async def delete_session(self, session_id: str) -> int:
        rows = await self._query(COLLECTION, f'session_id == "{session_id}"', ["seq"])
        dropped = len(rows)

        def _run() -> None:
            self._ensure_schema()
            client = self._ensure_client()
            client.delete(COLLECTION, filter=f'session_id == "{session_id}"')
            client.delete(SESSIONS_COLLECTION, filter=f'turn_id == "{session_id}"')
            # Standalone Milvus applies deletes asynchronously; flush makes
            # them visible so a read-after-delete sees the dropped rows gone
            # (embedded Lite is already immediate, flush is a no-op there).
            client.flush(COLLECTION)
            client.flush(SESSIONS_COLLECTION)

        await asyncio.to_thread(_run)
        self._seq_cache.pop(session_id, None)
        return dropped

    async def count_sessions(self) -> int:
        rows = await self._query(SESSIONS_COLLECTION, 'turn_id != ""', ["count(*)"])
        return int(rows[0]["count(*)"]) if rows else 0

    async def count_turns(self) -> int:
        rows = await self._query(COLLECTION, 'turn_id != ""', ["count(*)"])
        return int(rows[0]["count(*)"]) if rows else 0

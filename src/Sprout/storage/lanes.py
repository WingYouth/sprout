"""The six-lane fan-out: every write lands in every database it belongs to.

The data-layer plan (:mod:`Sprout.storage.plan`) names six databases —
SQLite, JSONL, BlobStore (authority lanes) and Redis, Milvus, Neo4j (derived
lanes). This module is the write-through engine that makes the plan real for
the three data categories the runtime produces:

===============  ===========================  =====================================
category         authority                    derived lanes
===============  ===========================  =====================================
session + turns  SessionStore (sqlite/jsonl/  redis hash+list (hot copy, TTL),
                 blobstore)                   milvus turn vectors, neo4j turn
                                              chain, sqlite FTS5 (turns)
memory facts     memory layer files           sqlite memory_fts, milvus fact
                 (MEMORY.md/USER.md)          vectors, neo4j fact nodes, redis
                                              block-cache invalidation
context          ContextStore (sqlite table  redis last-context cache, milvus
compositions     or jsonl log)                snapshot vectors, neo4j snapshot
                                              nodes, blobstore oversized bodies
===============  ===========================  =====================================

Two rules the fan-out enforces:

1. **Authority first, mirrors second.** The authority write must succeed;
   a failure there propagates. A failure in any derived lane is logged and
   swallowed — derived data is rebuildable, and a cold Redis must never take
   the online turn path down.
2. **Mirrors carry the authority's sequence.** After appending a turn the
   fan-out reads it back so every lane stores the same per-session ``seq``
   the authority assigned (backends honor ``turn.seq`` when it is nonzero).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from Sprout.session.models import Session, Turn
from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.contracts.vectors import KNOWLEDGE_CHUNKS, SESSION_TURNS
from Sprout.storage.embeddings import Embedder, HashingEmbedder

if TYPE_CHECKING:
    from Sprout.memory.contract import MemoryStore, SessionSearch
    from Sprout.memory.models import SessionFact, UserFact
    from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore
    from Sprout.rootstock.backends.redis_store import RedisSessionStore
    from Sprout.storage.contracts.blobs import BlobStore
    from Sprout.storage.contracts.cache import CacheStore
    from Sprout.storage.contracts.context import ContextStore
    from Sprout.storage.contracts.vectors import VectorStore
    from Sprout.storage.local.sqlite.memory_index import SqliteMemoryIndex

logger = logging.getLogger("Sprout.storage.lanes")

#: Vector namespaces used by the fan-out (one Milvus collection each).
MEMORY_FACTS_NS = KNOWLEDGE_CHUNKS
CONTEXT_SNAPSHOTS_NS = "context_snapshots"

#: Context bodies larger than this go to the blobstore out-of-line.
BLOB_THRESHOLD_BYTES = 65536

MEMORY_BLOCK_KEY = "sprout:memory:block:{owner}"
CONTEXT_KEY = "sprout:context:{session_id}"
CONTEXT_TTL_SECONDS = 86400


class SixLaneFanout:
    """A :class:`~Sprout.rootstock.contract.SessionStore` that mirrors writes.

    Reads always come from the authority. Writes go to the authority first,
    then fan out to whichever derived lanes are wired; each lane failure is
    logged and recorded in :attr:`last_errors` but never raised.
    """

    def __init__(
        self,
        authority: Any,
        *,
        redis: RedisSessionStore | None = None,
        graph: Neo4jSessionStore | None = None,
        vectors: VectorStore | None = None,
        fts: SessionSearch | None = None,
        blobs: BlobStore | None = None,
        context_store: ContextStore | None = None,
        memory_index: SqliteMemoryIndex | None = None,
        cache: CacheStore | None = None,
        embed: Embedder | None = None,
        blob_threshold: int = BLOB_THRESHOLD_BYTES,
    ) -> None:
        self.authority = authority
        self.redis = redis
        self.graph = graph
        self.vectors = vectors
        self.fts = fts
        self.blobs = blobs
        self.context_store = context_store
        self.memory_index = memory_index
        self.cache = cache
        self.embed = embed or HashingEmbedder()
        self.blob_threshold = blob_threshold
        self.last_errors: list[str] = []
        self._closed = False

    @property
    def database(self) -> Any:
        """The authority's SQLite handle, or ``None`` for in-memory backends.

        The outbox worker needs the conversation database to drain pending
        rows; it reaches it through the authority rather than the wrapper.
        """
        return getattr(self.authority, "database", None)

    # -- lane plumbing --------------------------------------------------------

    async def _mirror(self, lane: str, action) -> None:
        try:
            await action()
        except Exception as exc:  # noqa: BLE001 - derived lanes must not raise
            message = f"lane '{lane}' mirror failed: {type(exc).__name__}: {exc}"
            logger.warning("%s", message)
            self.last_errors.append(message)

    @property
    def active_lanes(self) -> dict[str, bool]:
        return {
            "authority": True,
            "redis": self.redis is not None or self.cache is not None,
            "sqlite-fts": self.fts is not None or self.memory_index is not None,
            "milvus": self.vectors is not None,
            "neo4j": self.graph is not None,
            "jsonl/blobstore": self.context_store is not None or self.blobs is not None,
        }

    # -- SessionStore protocol (authority-first, mirrors after) ---------------

    async def get_session(self, session_id: str) -> Session | None:
        return await self.authority.get_session(session_id)

    async def save_session(self, session: Session) -> None:
        await self.authority.save_session(session)
        if self.redis is not None:
            await self._mirror("redis.session", lambda: self.redis.save_session(session))
        if self.graph is not None:
            await self._mirror("neo4j.session", lambda: self.graph.save_session(session))

    async def append_turn(self, turn: Turn) -> None:
        await self.authority.append_turn(turn)
        # Read back so mirrors carry the seq the authority assigned.
        recent = await self.authority.recent_turns(turn.session_id, limit=1)
        stored = recent[-1] if recent else turn
        if self.redis is not None:
            await self._mirror("redis.turn", lambda: self.redis.append_turn(stored))
        if self.graph is not None:
            await self._mirror("neo4j.turn", lambda: self.graph.append_turn(stored))
        if self.fts is not None:
            async def _index() -> None:
                await self.fts.index_turn(
                    session_id=stored.session_id,
                    turn_id=stored.id,
                    turn_seq=stored.seq,
                    role=stored.role,
                    body=stored.content,
                )

            await self._mirror("fts.turn", _index)
        if self.vectors is not None:
            vector = self.embed(stored.content)
            # The envelope subset (channel, message id) rides along so semantic
            # recall can be filtered/attributed without re-reading the
            # authority (MESSAGE_PERSISTENCE.md M4).
            vector_metadata: dict[str, Any] = {
                "session_id": stored.session_id,
                "seq": stored.seq,
                "role": stored.role,
            }
            for key in ("channel", "message_id", "correlation_id"):
                value = stored.metadata.get(key)
                if value is not None:
                    vector_metadata[key] = value

            async def _upsert() -> None:
                await self.vectors.upsert(
                    stored.id,
                    vector,
                    namespace=SESSION_TURNS,
                    metadata=vector_metadata,
                )

            await self._mirror("milvus.turn", _upsert)

    async def save_attachment(
        self,
        attachment: Any,
        *,
        message_id: str,
        kind: str = "",
        content_hash: str = "",
        scan_status: str = "unscanned",
        metadata: Any = None,
    ) -> None:
        """Persist an attachment row on the authority.

        The §19.2 attachment table lives only in the conversation authority, so
        this delegates rather than mirroring. Without it the online write path
        raises ``AttributeError`` and the fail-open attachment lane silently
        drops every attachment.
        """
        await self.authority.save_attachment(
            attachment,
            message_id=message_id,
            kind=kind,
            content_hash=content_hash,
            scan_status=scan_status,
            metadata=metadata,
        )

    async def attachments_for_message(self, message_id: str) -> list[dict[str, Any]]:
        return await self.authority.attachments_for_message(message_id)

    async def recent_turns(self, session_id: str, limit: int = 20):
        return await self.authority.recent_turns(session_id, limit)

    async def turns_before(self, session_id: str, seq: int, limit: int = 100):
        return await self.authority.turns_before(session_id, seq, limit)

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Forward to the authority (see the contract).

        This wrapper is what ``sessions`` actually points at whenever the
        fan-out is wired, so without the forward the cascade's
        ``getattr(..., None)`` probe found nothing on exactly the deployments
        that have a blobstore to leak into.
        """
        collect = getattr(self.authority, "session_blob_uris", None)
        if not callable(collect):
            return []
        return await collect(session_id)

    async def delete_session(self, session_id: str) -> int:
        # Collect turn ids first: vector keys are gone once the authority drops.
        turns = await self.authority.turns_before(session_id, seq=10**12, limit=10**6)
        keys = [turn.id for turn in turns]
        dropped = await self.authority.delete_session(session_id)

        if self.redis is not None:
            await self._mirror("redis.drop", lambda: self.redis.delete_session(session_id))
        if self.graph is not None:
            await self._mirror(
                "neo4j.drop", lambda: self.graph.delete_session(session_id)
            )
        if self.fts is not None:
            await self._mirror("fts.drop", lambda: self.fts.unindex_session(session_id))
        if self.vectors is not None:
            async def _drop_vectors() -> None:
                for key in keys:
                    await self.vectors.delete(key, namespace=SESSION_TURNS)

            await self._mirror("milvus.drop", _drop_vectors)
        if self.cache is not None:
            key = CONTEXT_KEY.format(session_id=session_id)
            await self._mirror("cache.drop", lambda: self.cache.delete(key))
        return dropped

    async def count_sessions(self) -> int:
        return await self.authority.count_sessions()

    async def count_turns(self) -> int:
        return await self.authority.count_turns()

    # -- memory-layer mirroring ------------------------------------------------

    async def mirror_fact(self, fact: SessionFact | UserFact) -> None:
        """Fan one curated memory fact out to every derived lane."""
        scope = "session" if hasattr(fact, "session_id") else "user"
        owner = fact.session_id if scope == "session" else fact.user_id  # type: ignore[attr-defined]
        body = f"{fact.key}: {fact.value}"

        if self.memory_index is not None:
            await self._mirror(
                "memory_fts.index",
                lambda: self.memory_index.index_fact(scope, owner, fact.key, body),
            )
        if self.vectors is not None:
            vector = self.embed(body)
            key = f"fact:{scope}:{owner}:{fact.key}"

            async def _upsert() -> None:
                await self.vectors.upsert(
                    key,
                    vector,
                    namespace=MEMORY_FACTS_NS,
                    metadata={"scope": scope, "owner": owner, "key": fact.key},
                )

            await self._mirror("milvus.fact", _upsert)
        if self.graph is not None:
            async def _project() -> None:
                await self.graph.merge_node(
                    "MemoryFact",
                    "fact_key",
                    {
                        "fact_key": f"{scope}:{owner}:{fact.key}",
                        "scope": scope,
                        "owner": owner,
                        "body": body,
                    },
                )
                if scope == "session":
                    await self.graph.merge_relation(
                        "MemoryFact",
                        f"session:{owner}:{fact.key}",
                        "OF_SESSION",
                        "Session",
                        owner,
                        src_prop="fact_key",
                    )
                else:
                    await self.graph.merge_node("User", "id", {"id": owner})
                    await self.graph.merge_relation(
                        "MemoryFact",
                        f"user:{owner}:{fact.key}",
                        "OF_USER",
                        "User",
                        owner,
                        src_prop="fact_key",
                    )

            await self._mirror("neo4j.fact", _project)
        # Any edit invalidates the cached rendered block for that owner.
        if self.cache is not None:
            await self._mirror(
                "redis.invalidate",
                lambda: self.cache.delete(MEMORY_BLOCK_KEY.format(owner=owner)),
            )

    async def resync_facts(
        self, facts: list[SessionFact] | list[UserFact]
    ) -> None:
        """Rebuild every derived lane for one owner from the authority list.

        Called after substring-based removals (which cannot name the exact
        keys they dropped): the lanes are dropped per-owner and re-indexed
        from the surviving facts.
        """
        if not facts:
            return
        first = facts[0]
        scope = "session" if hasattr(first, "session_id") else "user"
        owner = first.session_id if scope == "session" else first.user_id  # type: ignore[attr-defined]

        if self.memory_index is not None:
            async def _reindex() -> None:
                await self.memory_index.drop_owner(scope, owner)
                for fact in facts:
                    await self.memory_index.index_fact(
                        scope, owner, fact.key, f"{fact.key}: {fact.value}"
                    )

            await self._mirror("memory_fts.resync", _reindex)
        if self.graph is not None:
            async def _reproject() -> None:
                await self.graph.drop_node("MemoryFact", "owner", owner)
                for fact in facts:
                    await self.mirror_fact(fact)

            await self._mirror("neo4j.resync", _reproject)

    async def cache_memory_block(self, owner: str, text: str, version: str) -> None:
        """Keep the rendered memory block hot in Redis for prefix-cache hits."""
        if self.cache is None:
            return
        await self._mirror(
            "redis.block",
            lambda: self.cache.set(
                MEMORY_BLOCK_KEY.format(owner=owner),
                {"version": version, "text": text},
                ttl_seconds=CONTEXT_TTL_SECONDS,
            ),
        )

    # -- context-layer persistence ---------------------------------------------

    async def persist_context(self, record: ContextRecord) -> ContextRecord:
        """Land one context composition in its authority plus every lane.

        Oversized bodies are written out-of-line to the blobstore and the
        record carries the resulting URI. Returns the (possibly amended)
        record that was persisted.
        """
        stored = record
        if (
            self.blobs is not None
            and len(record.text.encode("utf-8")) > self.blob_threshold
        ):
            try:
                uri = await self.blobs.put(record.text.encode("utf-8"), mime_type="text/markdown")
                stored = ContextRecord(
                    session_id=record.session_id,
                    snapshot_hash=record.snapshot_hash,
                    text=record.text,
                    turn_seq=record.turn_seq,
                    token_estimate=record.token_estimate,
                    created_at=record.created_at,
                    blob_uri=uri,
                )
            except Exception as exc:  # noqa: BLE001 - blobstore is a lane, not authority
                self.last_errors.append(
                    f"lane 'blobstore.context' failed: {type(exc).__name__}: {exc}"
                )
        if self.context_store is not None:
            await self.context_store.append(stored)
        if self.cache is not None:
            await self._mirror(
                "redis.context",
                lambda: self.cache.set(
                    CONTEXT_KEY.format(session_id=stored.session_id),
                    {"hash": stored.snapshot_hash, "text": stored.text},
                    ttl_seconds=CONTEXT_TTL_SECONDS,
                ),
            )
        if self.vectors is not None:
            vector = self.embed(stored.text)

            async def _upsert() -> None:
                await self.vectors.upsert(
                    f"context:{stored.session_id}:{stored.snapshot_hash[:16]}",
                    vector,
                    namespace=CONTEXT_SNAPSHOTS_NS,
                    metadata={"session_id": stored.session_id, "hash": stored.snapshot_hash},
                )

            await self._mirror("milvus.context", _upsert)
        if self.graph is not None:
            async def _project() -> None:
                await self.graph.merge_node(
                    "ContextSnapshot",
                    "hash",
                    {
                        "hash": stored.snapshot_hash,
                        "session_id": stored.session_id,
                        "turn_seq": stored.turn_seq,
                        "token_estimate": stored.token_estimate,
                        "created_at": stored.created_at.isoformat(),
                    },
                )
                await self.graph.merge_relation(
                    "ContextSnapshot",
                    stored.snapshot_hash,
                    "OF_SESSION",
                    "Session",
                    stored.session_id,
                    src_prop="hash",
                )

            await self._mirror("neo4j.context", _project)
        return stored

    async def latest_context(self, session_id: str) -> ContextRecord | None:
        if self.context_store is None:
            return None
        return await self.context_store.latest(session_id)

    async def close(self) -> None:
        """Close the authority and the redis session lane this fan-out owns.

        The bundle references the fan-out from both ``sessions`` and
        ``lanes``, so this must be idempotent. The graph, cache, and context
        stores are closed by their own bundle fields.
        """
        if self._closed:
            return
        self._closed = True
        for handle in (self.authority, self.redis):
            close = getattr(handle, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass


class MirroredMemoryStore:
    """Wrap a memory-layer authority so every write fans out to the lanes."""

    def __init__(self, authority: MemoryStore, lanes: SixLaneFanout) -> None:
        self._authority = authority
        self._lanes = lanes

    # -- delegation of reads ---------------------------------------------------

    async def list_session_facts(self, session_id: str):
        return await self._authority.list_session_facts(session_id)

    async def list_user_facts(self, user_id: str):
        return await self._authority.list_user_facts(user_id)

    async def snapshot_version(self) -> str:
        return await self._authority.snapshot_version()

    async def latest_session_summary(self, session_id: str):
        return await self._authority.latest_session_summary(session_id)

    async def save_session_summary(self, summary) -> None:
        await self._authority.save_session_summary(summary)

    # -- write-through with mirroring -------------------------------------------

    async def add_session_fact(self, fact, *, char_limit: int):
        rejected = await self._authority.add_session_fact(fact, char_limit=char_limit)
        if rejected is None:
            await self._lanes.mirror_fact(fact)
        return rejected

    async def add_user_fact(self, fact, *, char_limit: int):
        rejected = await self._authority.add_user_fact(fact, char_limit=char_limit)
        if rejected is None:
            await self._lanes.mirror_fact(fact)
        return rejected

    async def replace_session_fact(
        self, session_id: str, old_text: str, new_fact, *, char_limit: int
    ) -> bool:
        replaced = await self._authority.replace_session_fact(
            session_id, old_text, new_fact, char_limit=char_limit
        )
        if replaced:
            facts = await self._authority.list_session_facts(session_id)
            await self._lanes.resync_facts(facts)
        return replaced

    async def replace_user_fact(
        self, user_id: str, old_text: str, new_fact, *, char_limit: int
    ) -> bool:
        replaced = await self._authority.replace_user_fact(
            user_id, old_text, new_fact, char_limit=char_limit
        )
        if replaced:
            facts = await self._authority.list_user_facts(user_id)
            await self._lanes.resync_facts(facts)
        return replaced

    async def remove_session_fact(self, session_id: str, substring: str) -> int:
        removed = await self._authority.remove_session_fact(session_id, substring)
        if removed:
            facts = await self._authority.list_session_facts(session_id)
            await self._lanes.resync_facts(facts)
        return removed

    async def remove_user_fact(self, user_id: str, substring: str) -> int:
        removed = await self._authority.remove_user_fact(user_id, substring)
        if removed:
            facts = await self._authority.list_user_facts(user_id)
            await self._lanes.resync_facts(facts)
        return removed


__all__ = [
    "BLOB_THRESHOLD_BYTES",
    "CONTEXT_SNAPSHOTS_NS",
    "CONTEXT_TTL_SECONDS",
    "MEMORY_FACTS_NS",
    "MirroredMemoryStore",
    "SixLaneFanout",
]

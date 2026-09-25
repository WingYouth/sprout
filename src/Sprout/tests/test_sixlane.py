"""Six-lane storage tests: unit coverage with fakes plus live integration.

The unit tests run everywhere: they exercise the fan-out with in-memory
doubles and the local lanes (SQLite, JSONL, blobstore, FTS). The live tests
run only when the matching service is reachable, pointed at by env vars:

- ``SPROUT_TEST_REDIS_URL``  e.g. ``redis://localhost:6379/15``
- ``SPROUT_TEST_MILVUS_URL`` e.g. ``milvus:///D:/tmp/lite.db`` (embedded
  Milvus Lite) or ``http://localhost:19530`` (a standalone deployment)
- ``SPROUT_TEST_NEO4J_URL``  e.g. ``neo4j://localhost:7687`` with
  ``SPROUT_TEST_NEO4J_USER`` / ``SPROUT_TEST_NEO4J_PASSWORD``
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from Sprout.config.settings import StorageSettings
from Sprout.memory.models import SessionFact, UserFact
from Sprout.session.models import Session, Turn
from Sprout.storage.bundle import create_storage
from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.contracts.vectors import SESSION_TURNS
from Sprout.storage.embeddings import HashingEmbedder
from Sprout.storage.lanes import (
    CONTEXT_SNAPSHOTS_NS,
    MEMORY_FACTS_NS,
    MirroredMemoryStore,
    SixLaneFanout,
)
from Sprout.storage.local.filesystem.context import JsonlContextStore
from Sprout.storage.local.sqlite.context import SqliteContextStore
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.memory_index import SqliteMemoryIndex

REDIS_URL = os.environ.get("SPROUT_TEST_REDIS_URL", "")
MILVUS_URL = os.environ.get("SPROUT_TEST_MILVUS_URL", "")
NEO4J_URL = os.environ.get("SPROUT_TEST_NEO4J_URL", "")


# -- unit: the deterministic embedder ---------------------------------------


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dim=64)
    a = embedder("deploy the database lane")
    b = embedder("deploy the database lane")
    assert a == b
    assert len(a) == 64
    norm = sum(x * x for x in a) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-6)
    assert embedder("") == [0.0] * 64
    # Similar texts land closer than unrelated ones.
    near = embedder("deploy the database lanes")
    far = embedder("zzz qqq xxx yyy")
    da = sum((x - y) ** 2 for x, y in zip(a, near, strict=True))
    db = sum((x - y) ** 2 for x, y in zip(a, far, strict=True))
    assert da < db


def test_hashing_embedder_rejects_bad_dim() -> None:
    with pytest.raises(ValueError, match="positive"):
        HashingEmbedder(dim=0)


# -- unit: local context stores ---------------------------------------------


async def test_sqlite_context_store_round_trips_and_searches(tmp_path) -> None:
    db = SqliteDatabase.open(tmp_path / "ctx.db")
    store = SqliteContextStore(db)
    record = ContextRecord(
        session_id="s-1",
        snapshot_hash="abc",
        text="the model saw a summary of the deployment",
        turn_seq=3,
        token_estimate=42,
    )
    await store.append(record)
    await store.append(
        ContextRecord(session_id="s-1", snapshot_hash="def", text="second turn")
    )

    assert await store.count() == 2
    latest = await store.latest("s-1")
    assert latest is not None and latest.snapshot_hash == "def"
    hits = await store.search("deployment")
    assert len(hits) == 1 and hits[0].snapshot_hash == "abc"
    records = await store.list_records("s-1")
    assert [r.snapshot_hash for r in records] == ["abc", "def"]
    store.close()


async def test_jsonl_context_store_round_trips(tmp_path) -> None:
    store = JsonlContextStore(tmp_path / "ctx")
    await store.append(
        ContextRecord(session_id="s/1", snapshot_hash="h1", text="hello world")
    )
    await store.append(
        ContextRecord(session_id="s/1", snapshot_hash="h2", text="goodbye")
    )
    assert await store.count() == 2
    latest = await store.latest("s/1")
    assert latest is not None and latest.snapshot_hash == "h2"
    hits = await store.search("hello")
    assert len(hits) == 1 and hits[0].text == "hello world"
    # Session ids with separators are sanitized into safe file names.
    assert not list((tmp_path / "ctx").glob("**/*/*.jsonl"))


# -- unit: the memory FTS index ----------------------------------------------


async def test_sqlite_memory_index_round_trips(tmp_path) -> None:
    db = SqliteDatabase.open(tmp_path / "mem.db")
    index = SqliteMemoryIndex(db)
    await index.index_fact("session", "s-1", "deploy", "deploy: use the blue cluster")
    await index.index_fact("user", "u-1", "name", "name: R")

    assert await index.count() == 2
    hits = await index.search("blue")
    assert len(hits) == 1
    assert hits[0].scope == "session" and hits[0].fact_key == "deploy"

    # Re-indexing the same key replaces, not duplicates.
    await index.index_fact("session", "s-1", "deploy", "deploy: use green")
    assert await index.count() == 2
    assert await index.drop_owner("session", "s-1") == 1
    assert await index.count() == 1
    index_close = getattr(index, "close", None)
    if callable(index_close):
        index_close()
    db.close()


# -- unit: the fan-out with fakes --------------------------------------------


class _FakeVectorStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], tuple] = {}
        self.fail = False

    async def upsert(self, key, vector, *, namespace="session_turns", metadata=None):
        if self.fail:
            raise RuntimeError("vector lane down")
        self.items[(namespace, key)] = (vector, metadata or {})

    async def search(self, vector, limit=5, *, namespace="session_turns", filters=None):
        return []

    async def delete(self, key, *, namespace="session_turns"):
        return self.items.pop((namespace, key), None) is not None

    async def count(self, *, namespace=None):
        return len(self.items)


class _FakeSessionStore:
    """Minimal authority double implementing the SessionStore surface."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.turns: list[Turn] = []

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def save_session(self, session):
        self.sessions[session.id] = session

    async def append_turn(self, turn):
        seq = 1 + max((t.seq for t in self.turns if t.session_id == turn.session_id), default=0)
        stored = Turn(
            session_id=turn.session_id,
            role=turn.role,
            content=turn.content,
            id=turn.id,
            created_at=turn.created_at,
            seq=seq,
        )
        self.turns.append(stored)

    async def recent_turns(self, session_id, limit=20):
        mine = [t for t in self.turns if t.session_id == session_id]
        return mine[-limit:]

    async def turns_before(self, session_id, seq, limit=100):
        mine = [t for t in self.turns if t.session_id == session_id and t.seq < seq]
        return mine[:limit]

    async def delete_session(self, session_id):
        dropped = len([t for t in self.turns if t.session_id == session_id])
        self.turns = [t for t in self.turns if t.session_id != session_id]
        self.sessions.pop(session_id, None)
        return dropped

    async def count_sessions(self):
        return len(self.sessions)

    async def count_turns(self):
        return len(self.turns)


async def test_fanout_mirrors_turns_and_survives_lane_failure() -> None:
    authority = _FakeSessionStore()
    vectors = _FakeVectorStore()
    vectors.fail = True  # the vector lane is down; the authority must not care
    lanes = SixLaneFanout(authority, vectors=vectors, embed=HashingEmbedder(dim=8))

    await lanes.save_session(Session(id="s-1", user_id="u-1"))
    await lanes.append_turn(Turn("s-1", "user", "hello"))
    await lanes.append_turn(Turn("s-1", "assistant", "hi"))

    assert await lanes.count_turns() == 2
    assert [t.seq for t in await lanes.recent_turns("s-1")] == [1, 2]
    assert vectors.items == {}  # nothing landed, nothing crashed
    assert any("milvus.turn" in e for e in lanes.last_errors)


async def test_fanout_mirrors_turns_into_vectors_with_authority_seq() -> None:
    authority = _FakeSessionStore()
    vectors = _FakeVectorStore()
    lanes = SixLaneFanout(authority, vectors=vectors, embed=HashingEmbedder(dim=8))

    turn = Turn("s-1", "user", "hello")
    await lanes.append_turn(turn)
    (vector, metadata), *_ = vectors.items.values()
    assert metadata["seq"] == 1  # the authority's seq, not 0
    assert metadata["session_id"] == "s-1"
    assert len(vector) == 8

    dropped = await lanes.delete_session("s-1")
    assert dropped == 1
    assert vectors.items == {}


async def test_fanout_persists_context_to_all_local_lanes(tmp_path) -> None:
    authority = _FakeSessionStore()
    context_store = JsonlContextStore(tmp_path / "ctx")
    lanes = SixLaneFanout(
        authority,
        context_store=context_store,
        embed=HashingEmbedder(dim=8),
        blob_threshold=10,
    )
    record = ContextRecord(
        session_id="s-1",
        snapshot_hash="deadbeef",
        text="a context body far larger than the tiny test threshold",
    )
    stored = await lanes.persist_context(record)
    # Oversized body should NOT go to a blobstore that is not wired: the
    # record persists intact through the authority.
    assert stored.blob_uri is None
    assert await context_store.count() == 1


# -- unit: bundle wiring ------------------------------------------------------


async def test_create_storage_assembles_local_fanout_from_context_dsn(tmp_path) -> None:
    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        session=f"sqlite:///{tmp_path / 'session.db'}",
        cache="memory",
        context=f"jsonl://{tmp_path / 'context'}",
    )
    bundle = create_storage(settings)
    assert isinstance(bundle.sessions, SixLaneFanout)
    assert bundle.lanes is bundle.sessions
    assert bundle.context is not None
    assert bundle.memory_index is not None
    assert bundle.session_search is not None

    await bundle.sessions.save_session(Session(id="s-1", user_id="u-1"))
    await bundle.sessions.append_turn(Turn("s-1", "user", "hello six lanes"))

    # The authority lane: session.db has the row.
    with sqlite3.connect(str(tmp_path / "session.db")) as conn:
        rows = conn.execute("SELECT role, seq, content FROM turns").fetchall()
    assert rows == [("user", 1, "hello six lanes")]

    # The FTS lane indexed the turn.
    assert await bundle.session_search.search("six lanes")

    # The context lane recorded the (empty) first composition.
    record = ContextRecord(
        session_id="s-1", snapshot_hash="h", text="composed context"
    )
    await bundle.lanes.persist_context(record)
    assert await bundle.context.count() == 1

    await bundle.close()


async def test_mirrored_memory_store_fans_out_facts(tmp_path) -> None:
    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        session=f"sqlite:///{tmp_path / 'session.db'}",
        context=f"jsonl://{tmp_path / 'context'}",
    )
    bundle = create_storage(settings)
    lanes = bundle.lanes
    assert lanes is not None
    vectors = _FakeVectorStore()
    lanes.vectors = vectors

    fact = SessionFact(session_id="s-1", key="deploy", value="blue cluster")
    await lanes.mirror_fact(fact)
    assert any(ns == MEMORY_FACTS_NS for ns, _ in vectors.items)
    assert await bundle.memory_index.search("blue")

    user_fact = UserFact(user_id="u-1", key="name", value="R")
    await lanes.mirror_fact(user_fact)
    assert await bundle.memory_index.count() == 2

    await bundle.close()


# -- live: the three external databases ---------------------------------------


def _live(service: str) -> pytest.MarkDecorator:
    available = {
        "redis": bool(REDIS_URL),
        "milvus": bool(MILVUS_URL),
        "neo4j": bool(NEO4J_URL),
    }
    return pytest.mark.skipif(
        not available[service],
        reason=f"SPROUT_TEST_{service.upper()}_URL not set; live service not configured",
    )


async def _round_trip(store) -> None:
    session = Session(id="live-s-1", user_id="u-1", metadata={"channel": "test"})
    await store.save_session(session)
    await store.append_turn(Turn("live-s-1", "user", "hello live lane"))
    await store.append_turn(Turn("live-s-1", "assistant", "hi from the real db"))

    assert await store.count_sessions() >= 1
    assert await store.count_turns() >= 2
    loaded = await store.get_session("live-s-1")
    assert loaded is not None and loaded.metadata["channel"] == "test"
    turns = await store.recent_turns("live-s-1", limit=10)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert [t.seq for t in turns] == [1, 2]
    older = await store.turns_before("live-s-1", seq=2)
    assert [t.seq for t in older] == [1]

    dropped = await store.delete_session("live-s-1")
    assert dropped == 2
    assert await store.get_session("live-s-1") is None


@_live("redis")
async def test_redis_session_store_live_round_trip() -> None:
    from Sprout.rootstock.backends.redis_store import RedisSessionStore

    store = RedisSessionStore(REDIS_URL)
    await store.delete_session("live-s-1")
    await _round_trip(store)
    # The hot-cache key shape is part of the storage contract.
    assert await store.redis.exists("sprout:session:live-s-1") == 0
    await store.close()


@_live("milvus")
async def test_milvus_session_store_live_round_trip() -> None:
    from Sprout.rootstock.backends.milvus_store import MilvusSessionStore

    store = MilvusSessionStore(MILVUS_URL, embed=HashingEmbedder(dim=64), dim=64)
    await store.delete_session("live-s-1")
    await _round_trip(store)
    await store.close()


@_live("milvus")
async def test_milvus_vector_store_live_round_trip() -> None:
    from Sprout.storage.local.milvus.vectors import MilvusVectorStore

    store = MilvusVectorStore(MILVUS_URL, dim=64)
    embedder = HashingEmbedder(dim=64)
    await store.upsert("t-1", embedder("redis hot cache lane"), namespace=SESSION_TURNS,
                       metadata={"session_id": "live-s-1"})
    await store.upsert("t-2", embedder("totally unrelated words zzz"),
                       namespace=SESSION_TURNS, metadata={"session_id": "live-s-2"})

    hits = await store.search(
        embedder("redis hot cache lane"), limit=5, namespace=SESSION_TURNS
    )
    assert hits and hits[0].key == "t-1"
    filtered = await store.search(
        embedder("redis hot cache lane"), limit=5, namespace=SESSION_TURNS,
        filters={"session_id": "live-s-2"},
    )
    assert all(h.metadata.get("session_id") == "live-s-2" for h in filtered)

    assert await store.delete("t-1", namespace=SESSION_TURNS) is True
    assert await store.count(namespace=SESSION_TURNS) >= 1
    # Clean the lane so later live tests can assert exact counts.
    await store.delete("t-2", namespace=SESSION_TURNS)
    assert await store.count(namespace=SESSION_TURNS) == 0
    await store.close()


@_live("neo4j")
async def test_neo4j_session_store_live_round_trip() -> None:
    from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore

    dsn = NEO4J_URL
    user = os.environ.get("SPROUT_TEST_NEO4J_USER")
    password = os.environ.get("SPROUT_TEST_NEO4J_PASSWORD")
    if user:
        # Fold basic auth into the DSN the way the store parses it.
        dsn = dsn.replace("neo4j://", f"neo4j://{user}:{password or ''}@")
    store = Neo4jSessionStore(dsn)
    await store.delete_session("live-s-1")
    await _round_trip(store)

    # GraphStore contract on the live server.
    await store.merge_node("MemoryFact", "fact_key",
                           {"fact_key": "live:fact", "body": "blue cluster"})
    await store.merge_node("User", "id", {"id": "u-1"})
    await store.merge_relation("MemoryFact", "live:fact", "OF_USER", "User", "u-1",
                               src_prop="fact_key")
    assert await store.drop_node("MemoryFact", "fact_key", "live:fact") == 1
    await store.close()


@_live("redis")
@_live("milvus")
@_live("neo4j")
async def test_six_lanes_live_end_to_end(tmp_path) -> None:
    """All six databases, one fan-out, real data in every lane."""
    from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore
    from Sprout.rootstock.backends.redis_store import RedisSessionStore
    from Sprout.storage.local.milvus.vectors import MilvusVectorStore
    from Sprout.storage.local.redis.cache import RedisCacheStore

    embedder = HashingEmbedder(dim=64)
    milvus_vectors = MilvusVectorStore(MILVUS_URL, dim=64)
    redis_lane = RedisSessionStore(REDIS_URL)
    neo4j_lane = Neo4jSessionStore(
        NEO4J_URL.replace(
            "neo4j://",
            "neo4j://"
            f"{os.environ.get('SPROUT_TEST_NEO4J_USER', '')}:"
            f"{os.environ.get('SPROUT_TEST_NEO4J_PASSWORD', '')}@",
        )
        if os.environ.get("SPROUT_TEST_NEO4J_USER")
        else NEO4J_URL
    )
    cache = RedisCacheStore(REDIS_URL)
    context_store = SqliteContextStore(SqliteDatabase.open(tmp_path / "ctx.db"))

    authority = _FakeSessionStore()
    lanes = SixLaneFanout(
        authority,
        redis=redis_lane,
        graph=neo4j_lane,
        vectors=milvus_vectors,
        context_store=context_store,
        cache=cache,
        memory_index=SqliteMemoryIndex(SqliteDatabase.open(tmp_path / "mem.db")),
        embed=embedder,
    )

    session_id = "six-lane-live"
    await redis_lane.delete_session(session_id)
    await neo4j_lane.delete_session(session_id)

    await lanes.save_session(Session(id=session_id, user_id="u-1"))
    await lanes.append_turn(Turn(session_id, "user", "remember the blue cluster"))
    await lanes.mirror_fact(
        SessionFact(session_id=session_id, key="deploy", value="blue cluster")
    )
    await lanes.persist_context(
        ContextRecord(
            session_id=session_id,
            snapshot_hash="cafebabe",
            text="the model saw the blue cluster fact",
        )
    )

    # 1) SQLite lane: the fact index and the context snapshots.
    assert await lanes.memory_index.search("blue")
    assert await context_store.count() == 1
    # 2) Redis lane: the hot session copy and the context cache.
    assert await redis_lane.recent_turns(session_id)
    cached = await cache.get(f"sprout:context:{session_id}")
    assert cached and cached["hash"] == "cafebabe"
    # 3) Milvus lane: the turn vector, the fact vector, the context vector.
    assert await milvus_vectors.count(namespace=SESSION_TURNS) >= 1
    assert await milvus_vectors.count(namespace=MEMORY_FACTS_NS) >= 1
    assert await milvus_vectors.count(namespace=CONTEXT_SNAPSHOTS_NS) >= 1
    # 4) Neo4j lane: session, turn, fact, and context projection nodes.
    assert await neo4j_lane.count_sessions() >= 1
    assert await neo4j_lane.count_turns() >= 1
    records = await neo4j_lane._run(
        "MATCH (f:MemoryFact) WHERE f.owner = $owner RETURN count(f) AS total",
        {"owner": session_id},
    )
    assert records and int(records[0]["total"]) == 1
    records = await neo4j_lane._run(
        "MATCH (c:ContextSnapshot {hash: $hash}) RETURN count(c) AS total",
        {"hash": "cafebabe"},
    )
    assert records and int(records[0]["total"]) == 1

    assert lanes.last_errors == [], lanes.last_errors

    # Cascade delete cleans the derived lanes with the authority.
    await lanes.delete_session(session_id)
    assert await redis_lane.get_session(session_id) is None
    assert await milvus_vectors.count(namespace=SESSION_TURNS) == 0

    await lanes.close()
    await milvus_vectors.close()
    await cache.close()


# -- live: memory layer through the mirrored wrapper --------------------------


@_live("milvus")
async def test_mirrored_memory_store_live(tmp_path) -> None:
    from Sprout.memory.backends.memory_store import MemoryMemoryStore
    from Sprout.storage.local.milvus.vectors import MilvusVectorStore

    vectors = MilvusVectorStore(MILVUS_URL, dim=64)
    lanes = SixLaneFanout(
        _FakeSessionStore(),
        vectors=vectors,
        memory_index=SqliteMemoryIndex(SqliteDatabase.open(tmp_path / "mem.db")),
        embed=HashingEmbedder(dim=64),
    )
    authority = MemoryMemoryStore()
    mirrored = MirroredMemoryStore(authority, lanes)

    fact = SessionFact(session_id="s-mem", key="deploy", value="blue cluster")
    assert await mirrored.add_session_fact(fact, char_limit=1000) is None
    assert await vectors.count(namespace=MEMORY_FACTS_NS) >= 1
    assert await lanes.memory_index.search("blue")
    removed = await mirrored.remove_session_fact("s-mem", "blue")
    assert removed == 1
    await vectors.close()
    await lanes.close()

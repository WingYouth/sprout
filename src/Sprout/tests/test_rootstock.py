"""Rootstock tests: every session backend reserves its slot and round-trips.

The six slots the session layer must expose are sqlite, jsonl, blobstore,
milvus, neo4j, and redis. The three local ones are fully implemented; the
three external ones are reserved and must fail with an actionable message
rather than a surprise.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3

import pytest

from Sprout.config.settings import ObservationSettings, StorageSettings
from Sprout.rootstock import (
    BACKENDS,
    BlobSessionStore,
    JsonlSessionStore,
    MemorySessionStore,
    RootstockUnavailableError,
    SqliteSessionStore,
    create_session_store,
)
from Sprout.rootstock.backends.reserved import ReservedSessionStore
from Sprout.session.models import Session, Turn
from Sprout.storage.bundle import StorageBundle, create_storage, storage_status
from Sprout.storage.lanes import SixLaneFanout

_RESERVED = (("milvus", "pymilvus"), ("neo4j", "neo4j"), ("redis", "redis"))


def _tables(path) -> set[str]:
    with sqlite3.connect(str(path)) as conn:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


async def _round_trip(store) -> None:
    session = Session(id="s-1", user_id="u-1", metadata={"channel": "cli"})
    await store.save_session(session)
    await store.append_turn(Turn("s-1", "user", "hello"))
    await store.append_turn(Turn("s-1", "assistant", "hi there"))

    assert await store.count_sessions() == 1
    assert await store.count_turns() == 2
    loaded = await store.get_session("s-1")
    assert loaded is not None and loaded.metadata["channel"] == "cli"
    turns = await store.recent_turns("s-1")
    assert [turn.role for turn in turns] == ["user", "assistant"]


# -- sqlite ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_session_store_is_reserved_and_round_trips(tmp_path) -> None:
    path = tmp_path / "session.db"
    store = create_session_store(f"sqlite:///{path}")

    # Reserved on open: the file exists with the schema before any data.
    assert path.exists()
    assert {"sessions", "turns"} <= _tables(path)

    await _round_trip(store)
    store.close()

    reopened = create_session_store(f"sqlite:///{path}")
    assert await reopened.count_turns() == 2
    reopened.close()


# -- jsonl -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_jsonl_session_store_is_reserved_and_round_trips(tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    store = create_session_store(f"jsonl:///{path}")

    assert path.exists()
    await _round_trip(store)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["session", "turn", "turn"]

    # Reopening replays the log.
    reopened = create_session_store(f"jsonl:///{path}")
    assert await reopened.count_sessions() == 1
    assert await reopened.count_turns() == 2
    assert (await reopened.get_session("s-1")).user_id == "u-1"


@pytest.mark.asyncio
async def test_jsonl_session_store_assigns_and_persists_seq(tmp_path) -> None:
    """``seq`` is the only trustworthy ordering key; it must survive replay."""
    path = tmp_path / "session.jsonl"
    store = create_session_store(f"jsonl:///{path}")
    await store.save_session(Session(id="s-1", user_id="u-1"))
    await store.append_turn(Turn("s-1", "user", "one"))
    await store.append_turn(Turn("s-1", "assistant", "two"))
    await store.append_turn(Turn("s-1", "user", "three"))

    assert [t.seq for t in await store.recent_turns("s-1")] == [1, 2, 3]
    assert [t.seq for t in await store.turns_before("s-1", seq=3)] == [1, 2]

    reopened = create_session_store(f"jsonl:///{path}")
    assert [t.seq for t in await reopened.recent_turns("s-1")] == [1, 2, 3]
    assert [t.seq for t in await reopened.turns_before("s-1", seq=3)] == [1, 2]

    # Appends after reopen continue the monotonic sequence instead of
    # restarting at zero.
    await reopened.append_turn(Turn("s-1", "assistant", "four"))
    assert [t.seq for t in await reopened.recent_turns("s-1")] == [1, 2, 3, 4]

    # Deleting the session rewrites the log and drops the turns.
    assert await reopened.delete_session("s-1") == 4
    assert await reopened.count_turns() == 0


# -- blobstore -------------------------------------------------------------


@pytest.mark.asyncio
async def test_blobstore_session_store_is_reserved_and_round_trips(tmp_path) -> None:
    root = tmp_path / "session-blobs"
    store = create_session_store(f"blobstore:///{root}")

    # Reserved on open: index plus the blob directory.
    assert (root / "index.json").exists()
    assert (root / "blobs").is_dir()

    await _round_trip(store)

    reopened = create_session_store(f"blobstore:///{root}")
    assert await reopened.count_turns() == 2
    assert await reopened.count_sessions() == 1


@pytest.mark.asyncio
async def test_blobstore_session_store_supports_keyset_paging_and_delete(
    tmp_path,
) -> None:
    """The compactor pages with ``turns_before`` and the CLI cascades with
    ``delete_session``; the blobstore backend must implement both."""
    root = tmp_path / "session-blobs"
    store = create_session_store(f"blobstore:///{root}")
    await store.save_session(Session(id="s-1", user_id="u-1"))
    for body in ("one", "two", "three"):
        await store.append_turn(Turn("s-1", "user", body))

    assert [t.seq for t in await store.recent_turns("s-1")] == [1, 2, 3]
    assert [t.content for t in await store.turns_before("s-1", seq=3)] == [
        "one",
        "two",
    ]

    # The high-water mark is persisted in the index, so appends after reopen
    # continue the sequence.
    reopened = create_session_store(f"blobstore:///{root}")
    await reopened.append_turn(Turn("s-1", "assistant", "four"))
    assert [t.seq for t in await reopened.recent_turns("s-1")] == [1, 2, 3, 4]

    assert await reopened.delete_session("s-1") == 4
    assert await reopened.count_turns() == 0
    assert await reopened.get_session("s-1") is None


# -- memory ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_session_store_round_trips() -> None:
    store = MemorySessionStore()
    await _round_trip(store)
    assert await store.recent_turns("missing") == []


# -- reserved external backends --------------------------------------------


@pytest.mark.parametrize(("scheme", "package"), _RESERVED)
def test_reserved_backend_reports_missing_client(scheme: str, package: str) -> None:
    if importlib.util.find_spec(package) is not None:  # pragma: no cover
        pytest.skip(f"{package} is installed; adapter wiring is tested separately")
    with pytest.raises(RootstockUnavailableError, match=package):
        create_session_store(f"{scheme}://localhost:19530")


class _FakeReservedStore(ReservedSessionStore):
    """A reserved backend whose client package is present (stdlib ``json``)."""

    backend_name = "fake"
    required_package = "json"
    plan = "test double"


@pytest.mark.asyncio
async def test_reserved_backend_operations_explain_the_plan() -> None:
    store = _FakeReservedStore("fake://localhost")
    with pytest.raises(RootstockUnavailableError, match="not wired yet"):
        await store.save_session(Session(id="s", user_id="u"))
    with pytest.raises(RootstockUnavailableError, match="not wired yet"):
        await store.append_turn(Turn("s", "user", "hi"))


def test_reserved_backends_declare_their_storage_contract() -> None:
    """The reserved slots must spell out where data lands, not just exist."""
    from Sprout.rootstock.backends import milvus_store, neo4j_store, redis_store

    assert milvus_store.COLLECTION == "sprout_vec_messages"
    assert milvus_store.FIELDS["embedding"]["dim"] == milvus_store.EMBEDDING_DIM
    assert milvus_store.FIELDS["turn_id"]["is_primary"] is True

    assert redis_store.turns_key("s-1") == "sprout:session:s-1:turns"
    assert redis_store.session_key("s-1").startswith(redis_store.KEY_PREFIX)
    assert redis_store.MAX_CACHED_TURNS > 0
    assert redis_store.SESSION_TTL_SECONDS > 0

    assert len(neo4j_store.CONSTRAINTS) == 3
    assert "MERGE (s)-[:HAS_TURN]->(t)" in neo4j_store.MERGE_TURN
    assert neo4j_store.CONTENT_PREVIEW_CHARS > 0


# -- factory ---------------------------------------------------------------


def test_factory_dispatches_every_local_scheme(tmp_path) -> None:
    assert isinstance(create_session_store("memory://"), MemorySessionStore)
    assert isinstance(
        create_session_store(f"sqlite:///{tmp_path / 's.db'}"), SqliteSessionStore
    )
    assert isinstance(
        create_session_store(f"jsonl:///{tmp_path / 's.jsonl'}"), JsonlSessionStore
    )
    assert isinstance(
        create_session_store(f"blobstore:///{tmp_path / 'blobs'}"), BlobSessionStore
    )


def test_factory_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported session DSN"):
        create_session_store("postgres://localhost/x")


def test_factory_rejects_scheme_without_path() -> None:
    with pytest.raises(ValueError, match="needs a file path"):
        create_session_store("sqlite:///")


def test_backend_registry_lists_all_six_slots() -> None:
    assert set(BACKENDS) == {
        "sqlite",
        "jsonl",
        "blobstore",
        "milvus",
        "neo4j",
        "redis",
        "memory",
    }


def test_local_backends_implement_the_full_session_contract(tmp_path) -> None:
    """Every local backend must expose the whole SessionStore surface — the
    compactor calls ``turns_before`` and the CLI calls ``delete_session``
    without a hasattr guard."""
    stores = [
        create_session_store("memory://"),
        create_session_store(f"sqlite:///{tmp_path / 's.db'}"),
        create_session_store(f"jsonl:///{tmp_path / 's.jsonl'}"),
        create_session_store(f"blobstore:///{tmp_path / 'blobs'}"),
    ]
    for store in stores:
        for method in (
            "get_session",
            "save_session",
            "append_turn",
            "recent_turns",
            "turns_before",
            "delete_session",
            "count_sessions",
            "count_turns",
        ):
            assert callable(getattr(store, method, None)), (
                f"{type(store).__name__} lacks {method}"
            )
    stores[1].close()


# -- bundle wiring ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_storage_reserves_the_session_database(tmp_path) -> None:
    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        observations=ObservationSettings(dsn=f"sqlite:///{tmp_path / 'observations.db'}"),
        session=f"sqlite:///{tmp_path / 'session.db'}",
        cache="memory",
        blobs_dir=str(tmp_path / "media"),
    )
    bundle = create_storage(settings)

    assert (tmp_path / "session.db").exists()
    # Context 落库默认开启，会话门面因此是 SixLaneFanout；其 authority 仍是 sqlite。
    assert isinstance(bundle.sessions, SixLaneFanout)
    assert isinstance(bundle.sessions.authority, SqliteSessionStore)

    status = await storage_status(bundle)
    assert status["session_layer"]["backend"] == "SixLaneFanout"
    assert status["operational"]["sessions"] == 0

    await bundle.close()


@pytest.mark.asyncio
async def test_bundle_falls_back_to_operational_without_session_layer() -> None:
    bundle = StorageBundle.in_memory()
    assert bundle.sessions is not None
    # Simulating a bundle assembled before the session layer existed.
    bundle.sessions = None
    assert bundle.session_store() is bundle.operational

"""Reserved-database tests: every SQLite store opens, creates schema, and round-trips.

This is the acceptance test for the "预留数据库" requirement: runtime.db,
knowledge.db, and observations.db are all reserved on open (directory +
tables), before any data is written.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from Sprout.config.settings import ObservationSettings, StorageSettings
from Sprout.events.event import Event
from Sprout.security.approval import ApprovalManager, ApprovalStatus
from Sprout.session.models import Session, Turn
from Sprout.storage.bundle import StorageBundle, create_storage, storage_status
from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.contracts.observations import ReflectionRecord
from Sprout.storage.contracts.operational import Task
from Sprout.storage.local.filesystem.blobs import FileBlobStore
from Sprout.storage.local.sqlite.knowledge import open_knowledge_store
from Sprout.storage.local.sqlite.observations import open_observation_store
from Sprout.storage.local.sqlite.operational import open_operational_store


def _tables(path) -> set[str]:
    with sqlite3.connect(str(path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(path, table: str) -> set[str]:
    with sqlite3.connect(str(path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


# -- runtime.db (operational) ----------------------------------------------------


@pytest.mark.asyncio
async def test_operational_db_is_reserved_and_round_trips(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    store = open_operational_store(str(path))

    # Reserved on open: file exists with the full schema before any data.
    assert path.exists()
    assert {"sessions", "turns", "approvals", "tasks"} <= _tables(path)

    session = Session(id="s-1", user_id="u-1", metadata={"channel": "cli"})
    await store.save_session(session)
    await store.append_turn(Turn("s-1", "user", "hello"))
    await store.append_turn(Turn("s-1", "assistant", "hi there"))

    assert await store.count_sessions() == 1
    assert await store.count_turns() == 2
    loaded_session = await store.get_session("s-1")
    assert loaded_session is not None and loaded_session.metadata["channel"] == "cli"
    turns = await store.recent_turns("s-1")
    assert [turn.role for turn in turns] == ["user", "assistant"]

    # Tasks round-trip.
    task = Task(name="digest", payload={"when": "daily"})
    await store.save_task(task)
    loaded_task = await store.get_task(task.id)
    assert loaded_task is not None and loaded_task.payload == {"when": "daily"}
    assert len(await store.list_tasks()) == 1

    # Approvals round-trip (the store backs ApprovalManager).
    manager = ApprovalManager(store)
    record = await manager.request("deploy", {"env": "prod"})
    await manager.decide(record.id, True)
    found = await store.find_approval(
        "deploy", ApprovalManager.fingerprint({"env": "prod"}), ApprovalStatus.APPROVED
    )
    assert found is not None and found.id == record.id
    assert found.decided_by == "human"
    assert not await store.save_approval_if_status(found, ApprovalStatus.PENDING)
    found.status = ApprovalStatus.CONSUMED
    assert await store.save_approval_if_status(found, ApprovalStatus.APPROVED)
    assert (await store.get_approval(record.id)).status is ApprovalStatus.CONSUMED
    store.close()

    # Reopening keeps data: the reservation is a real persistent database.
    reopened = open_operational_store(str(path))
    assert await reopened.count_turns() == 2
    reopened.close()


@pytest.mark.asyncio
async def test_sqlite_approval_is_consumed_once_across_managers(tmp_path) -> None:
    store = open_operational_store(str(tmp_path / "approval-race.db"))
    first = ApprovalManager(store)
    second = ApprovalManager(store)
    record = await first.request("deploy", {"env": "prod"}, task_id="task-1")
    await first.decide(record.id, True)

    results = await asyncio.gather(
        first.is_approved("deploy", {"env": "prod"}, task_id="task-1"),
        second.is_approved("deploy", {"env": "prod"}, task_id="task-1"),
    )

    assert sorted(results) == [False, True]
    stored = await store.get_approval(record.id)
    assert stored is not None and stored.status is ApprovalStatus.CONSUMED
    store.close()


def test_operational_store_migrates_legacy_approval_scope_columns(tmp_path) -> None:
    path = tmp_path / "legacy-audit.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE approvals ("
            "id TEXT PRIMARY KEY, tool TEXT NOT NULL, "
            "arguments_fingerprint TEXT NOT NULL, status TEXT NOT NULL, "
            "requested_by TEXT NOT NULL DEFAULT 'system', decided_by TEXT, "
            "reason TEXT, created_at TEXT NOT NULL, decided_at TEXT, "
            "task_id TEXT NOT NULL DEFAULT '', single_use INTEGER NOT NULL DEFAULT 1, "
            "expires_at TEXT, used_at TEXT, resource_scope TEXT NOT NULL DEFAULT '', "
            "action_hash TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'unknown', "
            "action_summary TEXT NOT NULL DEFAULT '')"
        )

    store = open_operational_store(str(path))
    try:
        assert {"session_id", "approval_class"} <= _columns(path, "approvals")
    finally:
        store.close()


# -- knowledge.db ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_db_is_reserved_and_round_trips(tmp_path) -> None:
    path = tmp_path / "knowledge.db"
    store = open_knowledge_store(str(path))

    assert path.exists()
    assert {"knowledge"} <= _tables(path)

    await store.put(
        KnowledgeItem(id="k-1", content="SQLite storage keeps data local", kind="knowledge")
    )
    await store.put(
        KnowledgeItem(
            id="f-1", content="How do I reset a session? Delete runtime.db.", kind="faq"
        )
    )

    assert await store.count() == 2
    loaded = await store.get("k-1")
    assert loaded is not None and loaded.kind == "knowledge"

    hits = await store.search("SQLite local", limit=5)
    assert [item.id for item in hits] == ["k-1"]
    faqs = await store.list_items(kind="faq")
    assert [item.id for item in faqs] == ["f-1"]
    store.close()

    reopened = open_knowledge_store(str(path))
    assert await reopened.count() == 2
    reopened.close()


# -- observations.db ------------------------------------------------------------


@pytest.mark.asyncio
async def test_observations_db_is_reserved_and_round_trips(tmp_path) -> None:
    path = tmp_path / "observations.db"
    store = open_observation_store(str(path))

    assert path.exists()
    assert {"events", "reflections"} <= _tables(path)

    await store.append_event(Event("agent.failed", {"error_type": "ValueError"}, "corr-1"))
    await store.append_event(Event("message.sent", {}, "corr-1"))
    await store.append_reflection(ReflectionRecord(summary="two events", stats={"total": 2}))

    assert await store.count_events() == 2
    events = await store.list_events()
    assert [event.name for event in events] == ["agent.failed", "message.sent"]
    reflections = await store.list_reflections()
    assert len(reflections) == 1 and reflections[0].summary == "two events"
    store.close()

    reopened = open_observation_store(str(path))
    assert await reopened.count_events() == 2
    reopened.close()


# -- the whole bundle from settings -----------------------------------------------


@pytest.mark.asyncio
async def test_create_storage_reserves_all_databases(tmp_path) -> None:
    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        observations=ObservationSettings(dsn=f"sqlite:///{tmp_path / 'observations.db'}"),
        session=f"sqlite:///{tmp_path / 'session.db'}",
        cache="memory",
        blobs_dir=str(tmp_path / "media"),
    )
    bundle = create_storage(settings)

    for name in ("runtime.db", "knowledge.db", "observations.db", "session.db"):
        assert (tmp_path / name).exists(), f"{name} was not reserved"
    assert (tmp_path / "media").is_dir()

    status = await storage_status(bundle)
    assert status["operational"] == {"sessions": 0, "turns": 0, "tasks": 0, "approvals": 0}
    assert status["knowledge"] == 0
    assert status["events"] == 0

    await bundle.close()


@pytest.mark.asyncio
async def test_jsonl_context_dsn_uses_absolute_path(tmp_path) -> None:
    context_dir = tmp_path / "context"
    settings = StorageSettings(
        operational="memory",
        knowledge="memory",
        session="memory",
        cache="memory",
        context=f"jsonl://{context_dir}",
        blobs_dir=str(tmp_path / "media"),
    )
    bundle = create_storage(settings)

    await bundle.lanes.persist_context(
        ContextRecord(
            session_id="s-1",
            snapshot_hash="hash-1",
            text="hello context",
        )
    )

    assert (context_dir / "s-1.jsonl").is_file()
    # The DSN path is used verbatim, so the context must be absolute and must
    # not be reinterpreted relative to the process cwd.
    assert context_dir.is_absolute()

    await bundle.close()


@pytest.mark.asyncio
async def test_a_context_records_blob_uri_survives_the_round_trip(tmp_path) -> None:
    """``append`` wrote ``blob_uri``; the reader dropped it on the floor.

    The SQLite lane persisted the column but ``_row_to_record`` never read it
    back, so an offloaded context body came back as an unresolvable reference —
    and the session cascade, which reads records rather than rows, could not
    find the blob in order to delete it.
    """
    from Sprout.storage.local.sqlite.context import SqliteContextStore
    from Sprout.storage.local.sqlite.driver import SqliteDatabase

    store = SqliteContextStore(SqliteDatabase(str(tmp_path / "context.db")))
    await store.append(
        ContextRecord(
            session_id="s-1",
            snapshot_hash="hash-1",
            text="hello context",
            blob_uri="blob-abc123",
        )
    )

    latest = await store.latest("s-1")
    assert latest is not None
    assert latest.blob_uri == "blob-abc123"


def test_create_storage_rejects_unknown_dsn_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported operational DSN"):
        create_storage(StorageSettings(operational="postgres:///x", knowledge="memory"))


# -- blob store -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_blob_store_round_trip(tmp_path) -> None:
    blobs = FileBlobStore(tmp_path / "media")
    payload = b"hello media"

    uri = await blobs.put(payload, mime_type="text/plain")
    assert uri.endswith(".txt")
    assert await blobs.exists(uri)
    assert await blobs.get(uri) == payload
    assert await blobs.count() == 1

    # Content addressing: identical bytes deduplicate.
    again = await blobs.put(payload, mime_type="text/plain")
    assert again == uri
    assert await blobs.count() == 1

    assert await blobs.delete(uri) is True
    assert await blobs.delete(uri) is False
    assert await blobs.count() == 0


# -- in-memory bundle stays the default for tests --------------------------------


@pytest.mark.asyncio
async def test_in_memory_bundle_needs_no_files(tmp_path) -> None:
    bundle = StorageBundle.in_memory()
    await bundle.operational.save_session(Session(id="s", user_id="u"))
    assert await bundle.operational.count_sessions() == 1
    await bundle.close()
    assert list(tmp_path.iterdir()) == []

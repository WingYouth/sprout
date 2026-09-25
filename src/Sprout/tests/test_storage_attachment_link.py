"""§19.2 attachment + message↔task link authority tables (落库-2/4).

Verifies the two tables that had *no* schema at all — ``attachments`` (11 cols)
and ``message_task_link`` (5 cols) — now exist with the guidance.md §19.2
column contract, and that the runtime's online write path actually populates
them (attachment envelope lane + task-creation edge).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from Sprout.message.attachment import Attachment
from Sprout.message.models import Message
from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.runtime.runtime import Runtime
from Sprout.session.models import Turn
from Sprout.storage.local.sqlite.driver import SqliteDatabase

ATTACHMENT_COLUMNS = {
    "id",
    "message_id",
    "kind",
    "filename",
    "mime_type",
    "blob_uri",
    "size_bytes",
    "content_hash",
    "scan_status",
    "metadata_json",
    "created_at",
}
MESSAGE_TASK_LINK_COLUMNS = {
    "message_id",
    "task_id",
    "relation",
    "confidence",
    "created_at",
}


def _store(tmp_path) -> SqliteSessionStore:
    return SqliteSessionStore(SqliteDatabase(str(tmp_path / "conv.db")))


def _columns(store: SqliteSessionStore, table: str) -> set[str]:
    rows = store._db.fetchall_sync(f"PRAGMA table_info({table})")
    return {row["name"] for row in rows}


def test_attachment_table_has_authority_columns(tmp_path):
    store = _store(tmp_path)
    assert ATTACHMENT_COLUMNS <= _columns(store, "attachments")


def test_message_task_link_table_has_authority_columns(tmp_path):
    store = _store(tmp_path)
    assert MESSAGE_TASK_LINK_COLUMNS <= _columns(store, "message_task_link")


def test_attachment_round_trip_and_upsert(tmp_path):
    store = _store(tmp_path)
    attachment = Attachment(
        filename="report.pdf",
        mime_type="application/pdf",
        size=2048,
        uri="blob://report-1",
    )

    async def scenario() -> list[dict]:
        await store.save_attachment(
            attachment,
            message_id="turn-1",
            kind="document",
            content_hash="abc123",
            scan_status="clean",
            metadata={"uploaded_by": "cli"},
        )
        # Same id -> upsert, not a duplicate row.
        await store.save_attachment(
            attachment,
            message_id="turn-1",
            kind="document",
            content_hash="abc123",
            scan_status="clean",
        )
        return await store.attachments_for_message("turn-1")

    rows = asyncio.run(scenario())
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == attachment.id
    assert row["message_id"] == "turn-1"
    assert row["filename"] == "report.pdf"
    assert row["mime_type"] == "application/pdf"
    assert row["size_bytes"] == 2048
    assert row["blob_uri"] == "blob://report-1"
    assert row["content_hash"] == "abc123"
    assert row["scan_status"] == "clean"


def test_message_task_link_round_trip_is_idempotent(tmp_path):
    store = _store(tmp_path)

    async def scenario() -> list[dict]:
        await store.link_message_task("msg-1", "task-9", relation="created")
        await store.link_message_task(
            "msg-1", "task-9", relation="created", confidence=0.5
        )
        return await store.tasks_for_message("msg-1")

    rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert rows[0]["task_id"] == "task-9"
    assert rows[0]["relation"] == "created"
    assert rows[0]["confidence"] == 0.5  # last write wins


def test_runtime_persists_envelope_attachments(tmp_path):
    """The online write path stores metadata["attachments"] against the turn."""
    store = _store(tmp_path)
    turn = Turn("s1", "user", "see attachment")
    message = Message(
        content="see attachment",
        session_id="s1",
        metadata={
            "attachments": [
                {"id": "a1", "filename": "a.txt", "mime_type": "text/plain", "size": 3}
            ]
        },
    )

    fake_runtime = SimpleNamespace(_session_store=store)
    asyncio.run(Runtime._persist_attachments(fake_runtime, turn, message))

    rows = asyncio.run(store.attachments_for_message(turn.id))
    assert len(rows) == 1
    assert rows[0]["filename"] == "a.txt"


def test_runtime_attachment_lane_is_fail_open(tmp_path):
    """A malformed attachment entry never breaks the turn write."""
    store = _store(tmp_path)
    turn = Turn("s1", "user", "x")
    message = Message(
        content="x",
        session_id="s1",
        metadata={"attachments": ["not-a-mapping", {"id": "ok", "filename": "ok.txt"}]},
    )

    fake_runtime = SimpleNamespace(_session_store=store)
    asyncio.run(Runtime._persist_attachments(fake_runtime, turn, message))

    rows = asyncio.run(store.attachments_for_message(turn.id))
    assert [row["filename"] for row in rows] == ["ok.txt"]


def test_six_lane_fanout_delegates_attachment_writes(tmp_path):
    """The fanout wrapper must expose ``save_attachment``.

    Regression: ``SixLaneFanout`` implements the SessionStore protocol but
    originally omitted the §19.2 attachment methods, and ``_persist_attachments``
    is fail-open — so in any deployment with derived lanes wired the
    AttributeError was swallowed and *every* attachment was silently dropped.
    The unit tests above used a bare ``SqliteSessionStore`` mock and missed it.
    """
    from Sprout.storage.lanes import SixLaneFanout

    authority = _store(tmp_path)
    fanout = SixLaneFanout(authority)

    turn = Turn("s1", "user", "see attachment")
    message = Message(
        content="see attachment",
        session_id="s1",
        metadata={"attachments": [{"id": "a1", "filename": "a.txt", "size": 3}]},
    )

    fake_runtime = SimpleNamespace(_session_store=fanout)
    asyncio.run(Runtime._persist_attachments(fake_runtime, turn, message))

    rows = asyncio.run(fanout.attachments_for_message(turn.id))
    assert [row["filename"] for row in rows] == ["a.txt"]

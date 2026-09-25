"""§19.2 session/message authority columns — round-trip + migration (落库-1/2).

Verifies the guidance.md §19.2 column contract for ``sessions`` (11 cols) and
``turns`` (12 cols) is honoured end-to-end: model -> SQL -> read-back, plus the
in-place migration that upgrades pre-existing 4-column / 7-column databases.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime

from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.session.models import Session, Turn
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.turns import (
    migrate_sessions_columns,
    migrate_turns_message_columns,
    row_to_session,
)

SESSION_AUTHORITY_COLUMNS = {
    "channel",
    "target_ref_id",
    "title",
    "status",
    "locale",
    "summary",
    "updated_at",
}
TURN_MESSAGE_COLUMNS = {
    "content_type",
    "content_blob_uri",
    "line_count",
    "token_estimate",
    "language",
}


def test_session_authority_columns_round_trip(tmp_path):
    store = SqliteSessionStore(SqliteDatabase(str(tmp_path / "conv.db")))
    asyncio.run(
        store.save_session(
            Session(
                id="s1",
                user_id="u1",
                channel="cli",
                target_ref_id="ref-9",
                title="审查会话",
                status="active",
                locale="zh-CN",
                summary="一句话摘要",
            )
        )
    )
    got = asyncio.run(store.get_session("s1"))
    assert got is not None
    assert (got.channel, got.target_ref_id, got.title) == ("cli", "ref-9", "审查会话")
    assert (got.status, got.locale, got.summary) == ("active", "zh-CN", "一句话摘要")
    assert got.updated_at is None


def test_session_updated_at_round_trip(tmp_path):
    store = SqliteSessionStore(SqliteDatabase(str(tmp_path / "conv.db")))
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    asyncio.run(store.save_session(Session(id="s2", user_id="u1", updated_at=now)))
    got = asyncio.run(store.get_session("s2"))
    assert got is not None
    assert got.updated_at == now


def test_turn_message_columns_round_trip(tmp_path):
    store = SqliteSessionStore(SqliteDatabase(str(tmp_path / "conv.db")))
    asyncio.run(store.save_session(Session(id="s1", user_id="u1")))
    turn = Turn(
        "s1",
        "user",
        "line1\nline2\nline3",
        content_type="folded_block",
        line_count=3,
        token_estimate=7,
        language="zh-CN",
    )
    asyncio.run(store.append_turn(turn))
    got = asyncio.run(store.recent_turns("s1"))[0]
    assert got.content_type == "folded_block"
    assert got.line_count == 3
    assert got.token_estimate == 7
    assert got.language == "zh-CN"
    assert got.content_blob_uri is None


def test_every_document_backend_round_trips_the_message_columns(tmp_path):
    """The columns SQLite keeps must not evaporate in the JSON document stores.

    ``JsonlSessionStore`` and ``BlobSessionStore`` hand-rolled a seven-key
    document, so a turn read back from either lost its ``content_type``,
    ``content_blob_uri``, ``line_count``, ``token_estimate`` and ``language``.
    Field-level fidelity is what these stores advertise; dropping five columns
    silently is not a smaller store, it is a lossy one.
    """
    from Sprout.rootstock.backends.blob_store import BlobSessionStore
    from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
    from Sprout.storage.local.memory import MemoryBlobStore

    fields = ("content_type", "content_blob_uri", "line_count", "token_estimate", "language")
    expected = {
        "content_type": "folded_block",
        "content_blob_uri": "blob-abc",
        "line_count": 7,
        "token_estimate": 42,
        "language": "zh",
    }

    def _turn() -> Turn:
        return Turn("s1", "user", "body", seq=1, **expected)

    stores = [
        ("jsonl", JsonlSessionStore(str(tmp_path / "s.jsonl"))),
        (
            "blobstore",
            BlobSessionStore(str(tmp_path / "blobs"), MemoryBlobStore()),
        ),
    ]
    for label, store in stores:
        asyncio.run(store.append_turn(_turn()))
        got = asyncio.run(store.recent_turns("s1"))[0]
        for field in fields:
            assert getattr(got, field) == expected[field], (
                f"{label} lost {field}"
            )


def test_jsonl_replay_keeps_the_message_columns(tmp_path):
    """Reopening a JSONL file replays it; the replay must not drop columns."""
    from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore

    path = str(tmp_path / "s.jsonl")
    store = JsonlSessionStore(path)
    asyncio.run(
        store.append_turn(
            Turn("s1", "user", "body", seq=1, content_type="folded_block", line_count=3)
        )
    )

    reopened = JsonlSessionStore(path)  # replay from disk
    got = asyncio.run(reopened.recent_turns("s1"))[0]

    assert got.content_type == "folded_block"
    assert got.line_count == 3


def test_a_legacy_jsonl_record_still_loads(tmp_path):
    """A file written before these columns existed must not fail to replay."""
    import json

    from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore

    path = tmp_path / "legacy.jsonl"
    path.write_text(
        json.dumps(
            {
                "kind": "turn",
                "id": "t1",
                "session_id": "s1",
                "role": "user",
                "content": "old body",
                "created_at": "2026-01-01T00:00:00+00:00",
                "seq": 1,
                "metadata": {"channel": "cli"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    got = asyncio.run(JsonlSessionStore(str(path)).recent_turns("s1"))[0]

    assert got.content == "old body"
    assert got.metadata == {"channel": "cli"}
    # Absent keys fall back to the dataclass defaults rather than raising.
    assert got.content_type == "text"
    assert got.content_blob_uri is None


def test_migrate_legacy_sessions_and_turns(tmp_path):
    path = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, "
        "created_at TEXT, metadata_json TEXT)"
    )
    raw.execute(
        "CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, "
        "content TEXT, created_at TEXT, seq INTEGER, metadata_json TEXT)"
    )
    raw.execute(
        "INSERT INTO sessions VALUES ('s1', 'u1', '2026-01-01T00:00:00', '{}')"
    )
    raw.commit()
    raw.close()

    db = SqliteDatabase(path)
    migrate_sessions_columns(db)
    migrate_turns_message_columns(db)

    cols = {r["name"] for r in db.fetchall_sync("PRAGMA table_info(sessions)")}
    assert SESSION_AUTHORITY_COLUMNS <= cols
    tcols = {r["name"] for r in db.fetchall_sync("PRAGMA table_info(turns)")}
    assert TURN_MESSAGE_COLUMNS <= tcols

    row = db.fetchone_sync("SELECT * FROM sessions WHERE id='s1'")
    got = row_to_session(row)
    assert got.channel == ""
    assert got.status == "active"
    assert got.updated_at is None

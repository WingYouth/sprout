"""SQLite session store: the default local-first backend (sprout_conversation.db).

The schema mirrors the ``sessions``/``turns`` tables of the operational store,
so an existing ``sprout_audit.db`` can be adopted directly by pointing the session
DSN at it. Turns are ordered by a per-session monotonic ``seq`` — never by
wall-clock time alone.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from Sprout.message.attachment import Attachment
from Sprout.rootstock.contract import BLOB_URI_ENVELOPE_KEY
from Sprout.session.models import Session, Turn
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas
from Sprout.storage.local.sqlite.turns import (
    ATTACHMENTS_SCHEMA,
    MESSAGE_TASK_LINK_SCHEMA,
    SESSIONS_SCHEMA,
    TURNS_SCHEMA,
    migrate_sessions_columns,
    migrate_turns_envelope,
    migrate_turns_message_columns,
    migrate_turns_seq,
    row_to_session,
    row_to_turn,
)

# NOTE: Sprout.memory.outbox reaches back into this package for the shared
# turns helpers, so it is imported lazily inside the methods below; a
# module-level import here would close an import cycle at load time.

#: ``trigram`` rather than ``unicode61``: unicode61 treats a whole CJK sentence
#: as a single token, so ``sprout session search`` could never match a Chinese
#: sub-phrase. trigram handles CJK and English alike. This store is the first
#: creator of ``turns_fts``, so it is the one that decides — an existing
#: unicode61 database keeps its tokenizer (``IF NOT EXISTS``) rather than being
#: silently rebuilt.
SCHEMA = (
    SESSIONS_SCHEMA
    + TURNS_SCHEMA
    + ATTACHMENTS_SCHEMA
    + MESSAGE_TASK_LINK_SCHEMA
    + """
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED, turn_id UNINDEXED, role UNINDEXED,
    seq UNINDEXED, body, tokenize='trigram'
);
"""
)


def _row_to_turn(row) -> Turn:
    return row_to_turn(row)


class SqliteSessionStore:
    """Sessions and turns in one reserved SQLite database."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)
        migrate_turns_seq(db)
        migrate_turns_envelope(db)
        migrate_sessions_columns(db)
        migrate_turns_message_columns(db)
        from Sprout.memory.outbox import migrate_outbox

        migrate_outbox(db)

    @property
    def database(self) -> SqliteDatabase:
        """The backing SQLite handle.

        The outbox worker drains the ``outbox`` table through this handle;
        exposing it keeps the fan-out wrapper from reaching into a private
        attribute.
        """
        return self._db

    def close(self) -> None:
        self._db.close()

    async def get_session(self, session_id: str) -> Session | None:
        row = await self._db.fetchone(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        if row is None:
            return None
        return row_to_session(row)

    async def save_session(self, session: Session) -> None:
        await self._db.execute(
            "INSERT INTO sessions (id, user_id, created_at, metadata_json, "
            "channel, target_ref_id, title, status, locale, summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET user_id = excluded.user_id, "
            "metadata_json = excluded.metadata_json, "
            "channel = excluded.channel, "
            "target_ref_id = excluded.target_ref_id, "
            "title = excluded.title, "
            "status = excluded.status, "
            "locale = excluded.locale, "
            "summary = excluded.summary, "
            "updated_at = excluded.updated_at",
            (
                session.id,
                session.user_id,
                session.created_at.isoformat(),
                json.dumps(session.metadata, ensure_ascii=False, default=str),
                session.channel,
                session.target_ref_id,
                session.title,
                session.status,
                session.locale,
                session.summary,
                session.updated_at.isoformat() if session.updated_at else None,
            ),
        )

    async def append_turn(self, turn: Turn) -> None:
        # The turn and its outbox events go in one transaction, so a crash can
        # never strand a turn without its derived-layer counterparts.
        from Sprout.memory.outbox import append_turn_with_outbox

        await append_turn_with_outbox(self._db, turn)

    async def save_attachment(
        self,
        attachment: Attachment,
        *,
        message_id: str,
        kind: str = "",
        content_hash: str = "",
        scan_status: str = "unscanned",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Persist one §19.2 attachment row for ``message_id`` (a turn id)."""
        await self._db.execute(
            "INSERT INTO attachments (id, message_id, kind, filename, mime_type, "
            "blob_uri, size_bytes, content_hash, scan_status, metadata_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET message_id = excluded.message_id, "
            "kind = excluded.kind, filename = excluded.filename, "
            "mime_type = excluded.mime_type, blob_uri = excluded.blob_uri, "
            "size_bytes = excluded.size_bytes, content_hash = excluded.content_hash, "
            "scan_status = excluded.scan_status, "
            "metadata_json = excluded.metadata_json",
            (
                attachment.id,
                message_id,
                kind,
                attachment.filename,
                attachment.mime_type,
                attachment.uri,
                attachment.size,
                content_hash,
                scan_status,
                json.dumps(dict(metadata or {}), ensure_ascii=False, default=str),
                datetime.now(UTC).isoformat(),
            ),
        )

    async def attachments_for_message(self, message_id: str) -> list[dict[str, Any]]:
        """Return the §19.2 attachment rows bound to one message (turn id)."""
        rows = await self._db.fetchall(
            "SELECT * FROM attachments WHERE message_id = ? ORDER BY created_at",
            (message_id,),
        )
        return [dict(row) for row in rows]

    async def link_message_task(
        self,
        message_id: str,
        task_id: str,
        *,
        relation: str = "created",
        confidence: float = 1.0,
    ) -> None:
        """Record one §19.2 message↔task edge (idempotent per relation)."""
        await self._db.execute(
            "INSERT INTO message_task_link (message_id, task_id, relation, "
            "confidence, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id, task_id, relation) DO UPDATE SET "
            "confidence = excluded.confidence",
            (message_id, task_id, relation, confidence, datetime.now(UTC).isoformat()),
        )

    async def tasks_for_message(self, message_id: str) -> list[dict[str, Any]]:
        """Return the §19.2 message↔task edges for one message (turn id)."""
        rows = await self._db.fetchall(
            "SELECT * FROM message_task_link WHERE message_id = ? ORDER BY created_at",
            (message_id,),
        )
        return [dict(row) for row in rows]

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        rows = await self._db.fetchall(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        turns = [_row_to_turn(row) for row in rows]
        turns.reverse()
        return turns

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> list[Turn]:
        """Up to ``limit`` turns with ``seq`` below ``seq``, oldest first (keyset)."""
        rows = await self._db.fetchall(
            "SELECT * FROM turns WHERE session_id = ? AND seq < ? "
            "ORDER BY seq DESC LIMIT ?",
            (session_id, seq, limit),
        )
        turns = [_row_to_turn(row) for row in rows]
        turns.reverse()
        return turns

    async def delete_session(self, session_id: str) -> int:
        """Delete a session, its turns, and the per-turn derived rows.

        ``attachments.message_id`` and ``message_task_link.message_id`` both hold
        a turn id (§19.2), so both are keyed off this session's turns. Leaving
        them behind orphaned every attachment and task edge whose session had
        been removed.
        """
        before = int(await self._db.scalar(
            "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
        ) or 0)
        await self._db.execute_batch(
            [
                (
                    "DELETE FROM attachments WHERE message_id IN "
                    "(SELECT id FROM turns WHERE session_id = ?)",
                    (session_id,),
                ),
                (
                    "DELETE FROM message_task_link WHERE message_id IN "
                    "(SELECT id FROM turns WHERE session_id = ?)",
                    (session_id,),
                ),
                ("DELETE FROM turns WHERE session_id = ?", (session_id,)),
                ("DELETE FROM sessions WHERE id = ?", (session_id,)),
            ]
        )
        return before

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs referenced by this session's turns, for cascade cleanup.

        Offloaded bodies are content-addressed — the URI is a bare hash file
        name with no session component — so they cannot be found by prefix. The
        turns are the only index, and a URI can sit in either of two places: the
        ``content_blob_uri`` column, or the ``blob_uri`` envelope key that
        ``Runtime._offload_body`` actually writes. Both are read here; selecting
        only the column returned nothing for every body the runtime offloaded.
        """
        rows = await self._db.fetchall(
            "SELECT content_blob_uri, metadata_json FROM turns WHERE session_id = ?",
            (session_id,),
        )
        found: dict[str, None] = {}
        for row in rows:
            column = row["content_blob_uri"]
            if isinstance(column, str) and column:
                found.setdefault(column, None)
            envelope = _envelope_blob_uri(row["metadata_json"])
            if envelope:
                found.setdefault(envelope, None)
        return list(found)

    async def count_sessions(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM sessions") or 0)

    async def count_turns(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM turns") or 0)


def _envelope_blob_uri(raw_metadata: Any) -> str:
    """The ``blob_uri`` envelope key of a stored ``metadata_json`` column.

    Read straight from JSON rather than through ``row_to_turn`` so the cascade
    can select just the two columns it needs; a malformed envelope yields "",
    which reads as "this row references no blob" — the same answer the read side
    gives for an unresolvable reference.
    """
    if not raw_metadata:
        return ""
    try:
        envelope = json.loads(raw_metadata)
    except (TypeError, ValueError):
        return ""
    if not isinstance(envelope, dict):
        return ""
    uri = envelope.get(BLOB_URI_ENVELOPE_KEY)
    return uri if isinstance(uri, str) else ""


def open_session_store(
    path: str, pragmas: SqlitePragmas | None = None
) -> SqliteSessionStore:
    """Open (and reserve) a sprout_conversation.db at ``path``, creating the schema if needed."""
    return SqliteSessionStore(SqliteDatabase.open(path, pragmas))

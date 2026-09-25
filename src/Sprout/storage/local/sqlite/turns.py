"""Shared turns-table schema and the ``seq``/envelope migrations.

Both the rootstock session store (sprout_conversation.db) and the operational
store (sprout_audit.db) keep a ``turns`` table, so the schema fragment and the migrations
that add the monotonic ``seq`` column and the ``metadata_json`` envelope live
here exactly once.

Why ``seq``: ``created_at`` has millisecond resolution and wall-clock jumps
(NTP, clock rollback) can reorder turns; a per-session monotonic sequence is
the only ordering that cannot lie.

Why ``metadata_json``: the message envelope (channel, user_id, message_id,
correlation_id, blob references...) must survive the round trip into the
authority row — see ``Sprout.message.converter`` for the contract.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from Sprout.session.models import Session, Turn
from Sprout.storage.local.sqlite.driver import SqliteDatabase

#: §19.2 session authority columns beyond the original envelope columns.
SESSIONS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("channel", "TEXT NOT NULL DEFAULT ''"),
    ("target_ref_id", "TEXT"),
    ("title", "TEXT NOT NULL DEFAULT ''"),
    ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ("locale", "TEXT NOT NULL DEFAULT ''"),
    ("summary", "TEXT NOT NULL DEFAULT ''"),
    ("updated_at", "TEXT"),
)

SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    channel TEXT NOT NULL DEFAULT '',
    target_ref_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    locale TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);
"""


def migrate_sessions_columns(db: SqliteDatabase) -> None:
    """Add the §19.2 session columns to ``sessions`` on pre-existing databases."""
    rows = db.fetchall_sync("PRAGMA table_info(sessions)")
    if not rows:
        return
    columns = {row["name"] for row in rows}
    for name, ddl in SESSIONS_COLUMNS:
        if name not in columns:
            db.execute_sync(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")


#: §19.2 attachment authority — ``message_id`` references ``turns.id`` (this
#: project's message table); ``blob_uri`` offloads bytes to the blobstore.
ATTACHMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    blob_uri TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    scan_status TEXT NOT NULL DEFAULT 'unscanned',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
"""

#: §19.2 message↔task link; the two authorities live in different databases.
MESSAGE_TASK_LINK_SCHEMA = """
CREATE TABLE IF NOT EXISTS message_task_link (
    message_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, task_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_message_task_link_task ON message_task_link(task_id);
"""


#: §19.2 message authority columns beyond the original envelope columns.
#: ``content_type``/``line_count``/``language`` carry the CLI folded-paste
#: contract; ``content_blob_uri`` offloads large bodies; ``token_estimate``
#: feeds budget accounting.
TURNS_MESSAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("content_type", "TEXT NOT NULL DEFAULT 'text'"),
    ("content_blob_uri", "TEXT"),
    ("line_count", "INTEGER NOT NULL DEFAULT 0"),
    ("token_estimate", "INTEGER NOT NULL DEFAULT 0"),
    ("language", "TEXT NOT NULL DEFAULT ''"),
)

TURNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    content_type TEXT NOT NULL DEFAULT 'text',
    content_blob_uri TEXT,
    line_count INTEGER NOT NULL DEFAULT 0,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT ''
);
"""

SEQ_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_session_seq "
    "ON turns(session_id, seq)"
)

_APPEND_SQL = (
    "INSERT INTO turns (id, session_id, role, content, created_at, seq, "
    "metadata_json, content_type, content_blob_uri, line_count, "
    "token_estimate, language) "
    "VALUES (?, ?, ?, ?, ?, "
    "(SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE session_id = ?), ?, "
    "?, ?, ?, ?, ?)"
)


def migrate_turns_seq(db: SqliteDatabase) -> None:
    """Add and backfill ``turns.seq`` on databases created before it existed."""
    rows = db.fetchall_sync("PRAGMA table_info(turns)")
    if not rows:
        return
    columns = {row["name"] for row in rows}
    if "seq" not in columns:
        db.execute_sync("ALTER TABLE turns ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
        # Backfill: rank rows within each session by rowid (insertion order).
        db.execute_sync(
            "UPDATE turns SET seq = ("
            "SELECT COUNT(*) FROM turns t2 "
            "WHERE t2.session_id = turns.session_id AND t2.rowid <= turns.rowid)"
        )
    db.execute_sync(SEQ_INDEX)


def migrate_turns_envelope(db: SqliteDatabase) -> None:
    """Add ``turns.metadata_json`` on databases created before it existed."""
    rows = db.fetchall_sync("PRAGMA table_info(turns)")
    if not rows:
        return
    columns = {row["name"] for row in rows}
    if "metadata_json" not in columns:
        db.execute_sync(
            "ALTER TABLE turns ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
        )


def migrate_turns_message_columns(db: SqliteDatabase) -> None:
    """Add the §19.2 message columns to ``turns`` on pre-existing databases."""
    rows = db.fetchall_sync("PRAGMA table_info(turns)")
    if not rows:
        return
    columns = {row["name"] for row in rows}
    for name, ddl in TURNS_MESSAGE_COLUMNS:
        if name not in columns:
            db.execute_sync(f"ALTER TABLE turns ADD COLUMN {name} {ddl}")


def turn_metadata_json(turn: Turn) -> str:
    """Serialize the turn envelope; non-JSON-safe values fall back to ``str``."""
    return json.dumps(turn.metadata or {}, ensure_ascii=False, default=str)


def row_to_turn(row) -> Turn:
    """Map one ``turns`` row (any SQLite store) back to a :class:`Turn`."""
    keys = row.keys()
    raw_metadata = row["metadata_json"] if "metadata_json" in keys else None
    try:
        metadata = json.loads(raw_metadata) if raw_metadata else {}
    except (TypeError, ValueError):
        metadata = {}

    def _col(name: str, default):
        return row[name] if name in keys else default

    return Turn(
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        seq=row["seq"],
        metadata=metadata if isinstance(metadata, dict) else {},
        content_type=_col("content_type", "text"),
        content_blob_uri=_col("content_blob_uri", None),
        line_count=_col("line_count", 0),
        token_estimate=_col("token_estimate", 0),
        language=_col("language", ""),
    )


def row_to_session(row) -> Session:
    """Map one ``sessions`` row (any SQLite store) back to a :class:`Session`."""
    keys = row.keys()
    raw_metadata = row["metadata_json"] if "metadata_json" in keys else None
    try:
        metadata = json.loads(raw_metadata) if raw_metadata else {}
    except (TypeError, ValueError):
        metadata = {}

    def _col(name: str, default):
        return row[name] if name in keys else default

    raw_updated = _col("updated_at", None)
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        metadata=metadata if isinstance(metadata, dict) else {},
        channel=_col("channel", ""),
        target_ref_id=_col("target_ref_id", None),
        title=_col("title", ""),
        status=_col("status", "active"),
        locale=_col("locale", ""),
        summary=_col("summary", ""),
        updated_at=datetime.fromisoformat(raw_updated) if raw_updated else None,
    )


def turn_append_parameters(turn: Turn) -> tuple[object, ...]:
    """Bind values for ``_APPEND_SQL``.

    Shared by the plain writer and the outbox writer so their parameter order
    can never drift from the twelve placeholders in ``_APPEND_SQL``.
    """
    return (
        turn.id,
        turn.session_id,
        turn.role,
        turn.content,
        turn.created_at.isoformat(),
        turn.session_id,
        turn_metadata_json(turn),
        turn.content_type,
        turn.content_blob_uri,
        turn.line_count,
        turn.token_estimate,
        turn.language,
    )


async def append_turn(db: SqliteDatabase, turn: Turn, *, retries: int = 3) -> None:
    """Append ``turn`` with the next per-session ``seq``; retry on seq races."""
    parameters = turn_append_parameters(turn)
    for attempt in range(retries):
        try:
            await db.execute(_APPEND_SQL, parameters)
            return
        except sqlite3.IntegrityError:
            # Two processes computed the same next seq; recompute and retry.
            if attempt == retries - 1:
                raise

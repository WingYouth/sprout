"""SQLite context store: context snapshots plus FTS5 lookup in one database."""

from __future__ import annotations

from datetime import datetime

from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.local.sqlite.driver import SqliteDatabase

SCHEMA = """
CREATE TABLE IF NOT EXISTS context_snapshots (
    session_id TEXT NOT NULL,
    turn_seq INTEGER NOT NULL DEFAULT 0,
    snapshot_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    blob_uri TEXT
);
CREATE INDEX IF NOT EXISTS idx_context_session
    ON context_snapshots (session_id, created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
    session_id UNINDEXED, snapshot_hash UNINDEXED, text, tokenize='unicode61'
);
"""


def _row_to_record(row) -> ContextRecord:
    keys = row.keys()
    return ContextRecord(
        session_id=row["session_id"],
        snapshot_hash=row["snapshot_hash"],
        text=row["text"],
        turn_seq=int(row["turn_seq"]),
        token_estimate=int(row["token_estimate"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        # ``append`` has always written this column, but the reader dropped it,
        # so every offloaded context body came back as an unresolvable
        # reference — and the cascade, which reads the record rather than the
        # row, could not find the blob to delete it.
        blob_uri=row["blob_uri"] if "blob_uri" in keys else None,
    )


class SqliteContextStore:
    """Append-only context compositions with full-text search (SQLite lane)."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    async def append(self, record: ContextRecord) -> None:
        await self._db.execute_batch(
            [
                (
                    "INSERT INTO context_snapshots "
                    "(session_id, turn_seq, snapshot_hash, text, token_estimate, "
                    "created_at, blob_uri) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.session_id,
                        record.turn_seq,
                        record.snapshot_hash,
                        record.text,
                        record.token_estimate,
                        record.created_at.isoformat(),
                        record.blob_uri,
                    ),
                ),
                (
                    "INSERT INTO context_fts (session_id, snapshot_hash, text) "
                    "VALUES (?, ?, ?)",
                    (record.session_id, record.snapshot_hash, record.text),
                ),
            ]
        )

    async def latest(self, session_id: str) -> ContextRecord | None:
        row = await self._db.fetchone(
            "SELECT * FROM context_snapshots WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        return _row_to_record(row) if row is not None else None

    async def list_records(
        self, session_id: str, *, limit: int = 20
    ) -> list[ContextRecord]:
        rows = await self._db.fetchall(
            "SELECT * FROM context_snapshots WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        records = [_row_to_record(row) for row in rows]
        records.reverse()
        return records

    async def search(self, query: str, *, limit: int = 10) -> list[ContextRecord]:
        rows = await self._db.fetchall(
            "SELECT session_id, snapshot_hash, text FROM context_fts "
            "WHERE context_fts MATCH ? LIMIT ?",
            (query, limit),
        )
        return [
            ContextRecord(
                session_id=row["session_id"],
                snapshot_hash=row["snapshot_hash"],
                text=row["text"],
            )
            for row in rows
        ]

    async def count(self) -> int:
        return int(
            await self._db.scalar("SELECT COUNT(*) FROM context_snapshots") or 0
        )


__all__ = ["SCHEMA", "SqliteContextStore"]

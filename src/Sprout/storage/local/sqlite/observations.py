"""SQLite observation store: events and reflections (sprout_audit.db)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from Sprout.events.event import Event
from Sprout.storage.contracts.observations import ReflectionRecord
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(name, occurred_at);
CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    created_at TEXT NOT NULL
);
"""


class SqliteObservationStore:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    async def append_event(self, event: Event) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO events (id, name, payload_json, correlation_id, "
            "occurred_at) VALUES (?, ?, ?, ?, ?)",
            (
                event.id,
                event.name,
                json.dumps(dict(event.payload), ensure_ascii=False, default=str),
                event.correlation_id,
                event.occurred_at.isoformat(),
            ),
        )

    async def list_events(self, limit: int = 100) -> list[Event]:
        rows = await self._db.fetchall(
            "SELECT * FROM events ORDER BY occurred_at DESC LIMIT ?", (limit,)
        )
        events = [self._row_to_event(row) for row in rows]
        events.reverse()
        return events

    async def count_events(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM events") or 0)

    async def append_reflection(self, reflection: ReflectionRecord) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO reflections (id, summary, stats_json, correlation_id, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (
                reflection.id,
                reflection.summary,
                json.dumps(dict(reflection.stats), ensure_ascii=False, default=str),
                reflection.correlation_id,
                reflection.created_at.isoformat(),
            ),
        )

    async def list_reflections(self, limit: int = 50) -> list[ReflectionRecord]:
        rows = await self._db.fetchall(
            "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        reflections = [
            ReflectionRecord(
                summary=row["summary"],
                stats=json.loads(row["stats_json"]),
                correlation_id=row["correlation_id"],
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
        reflections.reverse()
        return reflections

    @staticmethod
    def _row_to_event(row: Mapping[str, Any]) -> Event:
        payload = json.loads(row["payload_json"])
        return Event(
            name=row["name"],
            payload=payload,
            correlation_id=row["correlation_id"],
            id=row["id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )


def open_observation_store(
    path: str, pragmas: SqlitePragmas | None = None
) -> SqliteObservationStore:
    """Open (and reserve) a sprout_audit.db at ``path``, creating the schema if needed."""
    return SqliteObservationStore(SqliteDatabase.open(path, pragmas))

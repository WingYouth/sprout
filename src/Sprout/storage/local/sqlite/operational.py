"""SQLite operational store: sessions, turns, approvals, and tasks (sprout_audit.db)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from Sprout.security.approval import ApprovalRecord, ApprovalStatus
from Sprout.session.models import Session, Turn
from Sprout.storage.contracts.operational import Task
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas
from Sprout.storage.local.sqlite.turns import (
    SESSIONS_SCHEMA,
    TURNS_SCHEMA,
    migrate_sessions_columns,
    migrate_turns_envelope,
    migrate_turns_message_columns,
    migrate_turns_seq,
    row_to_session,
    row_to_turn,
)
from Sprout.storage.local.sqlite.turns import (
    append_turn as _append_turn,
)

SCHEMA = (
    SESSIONS_SCHEMA
    + TURNS_SCHEMA
    + """
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    arguments_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL DEFAULT 'system',
    decided_by TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    task_id TEXT NOT NULL DEFAULT '',
    single_use INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    used_at TEXT,
    resource_scope TEXT NOT NULL DEFAULT '',
    action_hash TEXT NOT NULL DEFAULT '',
    action_summary TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'unknown',
    session_id TEXT NOT NULL DEFAULT '',
    approval_class TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_approvals_lookup
    ON approvals(tool, arguments_fingerprint, status, task_id);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_APPROVAL_COLUMNS: dict[str, str] = {
    "task_id": "ALTER TABLE approvals ADD COLUMN task_id TEXT NOT NULL DEFAULT ''",
    "single_use": "ALTER TABLE approvals ADD COLUMN single_use INTEGER NOT NULL DEFAULT 1",
    "expires_at": "ALTER TABLE approvals ADD COLUMN expires_at TEXT",
    "used_at": "ALTER TABLE approvals ADD COLUMN used_at TEXT",
    "resource_scope": "ALTER TABLE approvals ADD COLUMN resource_scope TEXT NOT NULL DEFAULT ''",
    "action_hash": "ALTER TABLE approvals ADD COLUMN action_hash TEXT NOT NULL DEFAULT ''",
    "action_summary": (
        "ALTER TABLE approvals ADD COLUMN action_summary TEXT NOT NULL DEFAULT ''"
    ),
    "source": "ALTER TABLE approvals ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'",
    "session_id": "ALTER TABLE approvals ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
    "approval_class": (
        "ALTER TABLE approvals ADD COLUMN approval_class TEXT NOT NULL DEFAULT ''"
    ),
}


class SqliteOperationalStore:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)
        migrate_turns_seq(db)
        migrate_turns_envelope(db)
        migrate_sessions_columns(db)
        migrate_turns_message_columns(db)
        self._migrate_approvals()

    def _migrate_approvals(self) -> None:
        """Add scoping columns to approval databases created before task binding."""
        rows = self._db.fetchall_sync("PRAGMA table_info(approvals)")
        existing = {row["name"] for row in rows} if rows else set()
        for column, statement in _APPROVAL_COLUMNS.items():
            if column not in existing:
                self._db.execute_sync(statement)
        self._db.execute_sync(
            "CREATE INDEX IF NOT EXISTS idx_approvals_reusable "
            "ON approvals(tool, approval_class, status, session_id, requested_by, "
            "source, resource_scope)"
        )

    def close(self) -> None:
        self._db.close()

    # Sessions and turns
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
                _dt(session.updated_at),
            ),
        )

    async def append_turn(self, turn: Turn) -> None:
        await _append_turn(self._db, turn)

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        rows = await self._db.fetchall(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        turns = [row_to_turn(row) for row in rows]
        turns.reverse()
        return turns

    async def count_sessions(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM sessions") or 0)

    async def count_turns(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM turns") or 0)

    # Approvals
    async def save_approval(self, record: ApprovalRecord) -> None:
        await self._db.execute(
            "INSERT INTO approvals (id, tool, arguments_fingerprint, status, "
            "requested_by, decided_by, reason, created_at, decided_at, "
            "task_id, single_use, expires_at, used_at, resource_scope, "
            "action_hash, action_summary, source, session_id, approval_class) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
            "decided_by = excluded.decided_by, reason = excluded.reason, "
            "decided_at = excluded.decided_at, task_id = excluded.task_id, "
            "single_use = excluded.single_use, expires_at = excluded.expires_at, "
            "used_at = excluded.used_at, resource_scope = excluded.resource_scope, "
            "action_hash = excluded.action_hash, "
            "action_summary = excluded.action_summary, source = excluded.source, "
            "session_id = excluded.session_id, "
            "approval_class = excluded.approval_class",
            (
                record.id,
                record.tool,
                record.arguments_fingerprint,
                record.status.value,
                record.requested_by,
                record.decided_by,
                record.reason,
                record.created_at.isoformat(),
                _dt(record.decided_at),
                record.task_id,
                int(record.single_use),
                _dt(record.expires_at),
                _dt(record.used_at),
                record.resource_scope,
                record.action_hash,
                record.action_summary,
                record.source,
                record.session_id,
                record.approval_class,
            ),
        )

    async def save_approval_if_status(
        self, record: ApprovalRecord, expected: ApprovalStatus
    ) -> bool:
        """Compare-and-set lifecycle state across all SQLite connections/processes."""
        changed = await self._db.execute(
            "UPDATE approvals SET status = ?, decided_by = ?, reason = ?, "
            "decided_at = ?, used_at = ?, expires_at = ? "
            "WHERE id = ? AND status = ?",
            (
                record.status.value,
                record.decided_by,
                record.reason,
                _dt(record.decided_at),
                _dt(record.used_at),
                _dt(record.expires_at),
                record.id,
                expected.value,
            ),
        )
        return changed == 1

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = await self._db.fetchone(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        )
        return self._row_to_approval(row) if row else None

    async def list_approvals(
        self, status: ApprovalStatus | None = None
    ) -> list[ApprovalRecord]:
        if status is None:
            rows = await self._db.fetchall(
                "SELECT * FROM approvals ORDER BY created_at DESC"
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            )
        return [self._row_to_approval(row) for row in rows]

    async def find_approval(
        self,
        tool: str,
        arguments_fingerprint: str,
        status: ApprovalStatus,
        task_id: str = "",
    ) -> ApprovalRecord | None:
        row = await self._db.fetchone(
            "SELECT * FROM approvals WHERE tool = ? AND arguments_fingerprint = ? "
            "AND status = ? AND task_id = ? ORDER BY created_at DESC LIMIT 1",
            (tool, arguments_fingerprint, status.value, task_id),
        )
        return self._row_to_approval(row) if row else None

    async def find_reusable_approval(
        self,
        tool: str,
        approval_class: str,
        status: ApprovalStatus,
        *,
        session_id: str,
        requested_by: str,
        source: str,
        task_id: str = "",
        resource_scope: str = "",
    ) -> ApprovalRecord | None:
        boundary_sql = "session_id = ?" if session_id else "task_id = ?"
        boundary_value = session_id or task_id
        row = await self._db.fetchone(
            "SELECT * FROM approvals WHERE tool = ? AND approval_class = ? "
            f"AND status = ? AND {boundary_sql} AND requested_by = ? "
            "AND source = ? AND resource_scope = ? AND single_use = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (
                tool,
                approval_class,
                status.value,
                boundary_value,
                requested_by,
                source,
                resource_scope,
            ),
        )
        return self._row_to_approval(row) if row else None

    @staticmethod
    def _row_to_approval(row: Any) -> ApprovalRecord:
        return ApprovalRecord(
            tool=row["tool"],
            arguments_fingerprint=row["arguments_fingerprint"],
            status=ApprovalStatus(row["status"]),
            requested_by=row["requested_by"],
            decided_by=row["decided_by"],
            reason=row["reason"],
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            decided_at=_parse_dt(row["decided_at"]),
            task_id=row["task_id"] or "",
            single_use=bool(row["single_use"]),
            expires_at=_parse_dt(row["expires_at"]),
            used_at=_parse_dt(row["used_at"]),
            resource_scope=row["resource_scope"] or "",
            action_hash=row["action_hash"] or "",
            # Tolerant of rows written before the column existed: the migration
            # backfills '' for them, and ``keys()`` guards a store whose schema
            # predates it entirely.
            action_summary=(
                row["action_summary"] or "" if "action_summary" in row.keys() else ""
            ),
            source=row["source"] or "unknown",
            session_id=row["session_id"] or "" if "session_id" in row.keys() else "",
            approval_class=(
                row["approval_class"] or "" if "approval_class" in row.keys() else ""
            ),
        )

    # Tasks
    async def save_task(self, task: Task) -> None:
        now = datetime.now(UTC)
        await self._db.execute(
            "INSERT INTO tasks (id, name, status, payload_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
            "payload_json = excluded.payload_json, updated_at = excluded.updated_at",
            (
                task.id,
                task.name,
                task.status,
                json.dumps(task.payload, ensure_ascii=False, default=str),
                task.created_at.isoformat(),
                (task.updated_at or now).isoformat(),
            ),
        )

    async def get_task(self, task_id: str) -> Task | None:
        row = await self._db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self._row_to_task(row) if row else None

    async def list_tasks(self, status: str | None = None) -> list[Task]:
        if status is None:
            rows = await self._db.fetchall(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return [self._row_to_task(row) for row in rows]

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        return Task(
            name=row["name"],
            payload=json.loads(row["payload_json"]),
            status=row["status"],
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )


def open_operational_store(
    path: str, pragmas: SqlitePragmas | None = None
) -> SqliteOperationalStore:
    """Open (and reserve) a sprout_audit.db at ``path``, creating the schema if needed."""
    return SqliteOperationalStore(SqliteDatabase.open(path, pragmas))

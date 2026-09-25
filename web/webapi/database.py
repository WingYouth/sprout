"""Reserved web-layer database.

The web application owns this SQLite database (``web/webapi/data/webapi.db``)
separately from the runtime's ``sprout_*`` and user ``project_*`` databases.
It is reserved for web-specific persistence:
request auditing today; web sessions, accounts, and preferences later.

Schema changes go through :data:`SCHEMA_VERSION` and :meth:`WebDatabase.initialize`,
which is the natural place to add migrations.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 3
_MISSING = object()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS web_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    route TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER,
    duration_ms REAL,
    session_id TEXT,
    user_id TEXT
);
CREATE TABLE IF NOT EXISTS web_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    priority TEXT NOT NULL DEFAULT 'medium',
    tags TEXT NOT NULL DEFAULT '[]',
    assignee TEXT,
    due_at TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS web_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    request_id TEXT
);
"""


class WebDatabase:
    """Async-friendly wrapper over the reserved web SQLite database."""

    def __init__(self, path: str | Path = "web/webapi/data/webapi.db") -> None:
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """Create the file, directories, and schema (idempotent)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            if row is None or row["v"] is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
                )
            elif int(row["v"]) < SCHEMA_VERSION:
                self._conn.execute(
                    "UPDATE schema_version SET version = ?, applied_at = ?",
                    (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
                )
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
            self._conn = None

    async def record_request(
        self,
        *,
        route: str,
        method: str,
        status_code: int | None = None,
        duration_ms: float | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._execute(
            "INSERT INTO web_requests (ts, route, method, status_code, duration_ms, "
            "session_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                route,
                method,
                status_code,
                duration_ms,
                session_id,
                user_id,
            ),
        )

    async def count_requests(self) -> int:
        return int(await self._scalar("SELECT COUNT(*) FROM web_requests") or 0)

    async def recent_requests(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM web_requests ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def touch_web_session(self, session_id: str, user_id: str | None) -> None:
        now = datetime.now(UTC).isoformat()
        await self._execute(
            "INSERT INTO web_sessions (id, user_id, created_at, last_seen_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            (session_id, user_id, now, now),
        )

    async def list_tasks(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM tasks ORDER BY created_at DESC")
        return [_task_from_row(row) for row in rows]

    async def create_task(
        self,
        *,
        title: str,
        description: str = "",
        status: str = "todo",
        priority: str = "medium",
        tags: list[str] | None = None,
        assignee: str | None = None,
        due_at: str | None = None,
        points: int = 0,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        task_id = uuid4().hex
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        completed_at = now if status == "done" else None
        await self._execute(
            "INSERT INTO tasks (id, title, description, status, priority, tags, "
            "assignee, due_at, points, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                title,
                description,
                status,
                priority,
                tags_json,
                assignee,
                due_at,
                points,
                now,
                now,
                completed_at,
            ),
        )
        return await self.get_task(task_id) or {}

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task_from_row(row) if row is not None else None

    async def update_task(
        self,
        task_id: str,
        *,
        title: str | None = _MISSING,
        description: str | None = _MISSING,
        status: str | None = _MISSING,
        priority: str | None = _MISSING,
        tags: list[str] | None = _MISSING,
        assignee: str | None = _MISSING,
        due_at: str | None = _MISSING,
        points: int | None = _MISSING,
    ) -> dict[str, Any] | None:
        current = await self.get_task(task_id)
        if current is None:
            return None
        updates: dict[str, Any] = {
            "title": title if title is not _MISSING else current["title"],
            "description": (
                description if description is not _MISSING else current["description"]
            ),
            "status": status if status is not _MISSING else current["status"],
            "priority": priority if priority is not _MISSING else current["priority"],
            "tags": json.dumps(
                tags if tags is not _MISSING else current.get("tags", []),
                ensure_ascii=False,
            ),
            "assignee": assignee if assignee is not _MISSING else current.get("assignee"),
            "due_at": due_at if due_at is not _MISSING else current.get("due_at"),
            "points": points if points is not _MISSING else current.get("points", 0),
        }
        now = datetime.now(UTC).isoformat()
        completed_at = now if updates["status"] == "done" else None
        await self._execute(
            "UPDATE tasks SET title = ?, description = ?, status = ?, priority = ?, "
            "tags = ?, assignee = ?, due_at = ?, points = ?, updated_at = ?, "
            "completed_at = ? WHERE id = ?",
            (
                updates["title"],
                updates["description"],
                updates["status"],
                updates["priority"],
                updates["tags"],
                updates["assignee"],
                updates["due_at"],
                updates["points"],
                now,
                completed_at,
                task_id,
            ),
        )
        return await self.get_task(task_id)

    async def delete_task(self, task_id: str) -> bool:
        current = await self.get_task(task_id)
        if current is None:
            return False
        await self._execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return True

    async def get_preferences(self) -> dict[str, Any]:
        rows = await self._fetchall("SELECT key, value FROM web_preferences")
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result

    async def set_preference(self, key: str, value: Any) -> None:
        await self._execute(
            "INSERT INTO web_preferences (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), datetime.now(UTC).isoformat()),
        )

    async def record_token_usage(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        request_id: str | None = None,
    ) -> None:
        await self._execute(
            "INSERT INTO token_usage (ts, provider, model, input_tokens, output_tokens, "
            "total_tokens, request_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                provider,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                request_id,
            ),
        )

    async def list_token_usage(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM token_usage ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def token_summary(self) -> dict[str, Any]:
        row = await self._fetchone(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(total_tokens), 0) AS total_tokens FROM token_usage"
        )
        return dict(row) if row is not None else {}

    # -- internals ---------------------------------------------------------
    def _require_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("WebDatabase is not initialized; call initialize() first")
        return self._conn

    async def _execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        def _run() -> None:
            with self._lock:
                conn = self._require_connection()
                conn.execute(sql, parameters)
                conn.commit()

        await asyncio.to_thread(_run)

    async def _fetchall(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        def _run() -> list[sqlite3.Row]:
            with self._lock:
                return self._require_connection().execute(sql, parameters).fetchall()

        return await asyncio.to_thread(_run)

    async def _fetchone(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        def _run() -> sqlite3.Row | None:
            with self._lock:
                return self._require_connection().execute(sql, parameters).fetchone()

        return await asyncio.to_thread(_run)

    async def _scalar(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        def _run() -> Any:
            with self._lock:
                row = self._require_connection().execute(sql, parameters).fetchone()
                return row[0] if row is not None else None

        return await asyncio.to_thread(_run)


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a tasks row into the JSON shape used by the API and frontend."""
    try:
        tags = json.loads(row["tags"])
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "tags": tags if isinstance(tags, list) else [],
        "assignee": row["assignee"],
        "due_at": row["due_at"],
        "points": row["points"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }

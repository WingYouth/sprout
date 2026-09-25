"""SQLite-backed LLM usage recorder."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    attempt INTEGER NOT NULL,
    error TEXT,
    duration_seconds REAL NOT NULL,
    retryable INTEGER NOT NULL
);
"""


class LLMUsageRecorder:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or Path.home() / ".sprout" / "data" / "sprout_usage.db")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO llm_usage "
                    "(ts, provider, model, input_tokens, output_tokens, total_tokens) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        provider,
                        model,
                        input_tokens,
                        output_tokens,
                        total_tokens,
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                # Usage is observability only. A read-only or unavailable usage
                # lane must never turn a successful model response into a model
                # provider failure.
                self._conn.rollback()

    def record_attempt(
        self,
        *,
        provider: str,
        model: str,
        attempt: int,
        error: str,
        duration_seconds: float,
        retryable: bool,
    ) -> None:
        """Persist one failed provider attempt for observability."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO llm_attempts "
                    "(ts, provider, model, attempt, error, duration_seconds, retryable) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        provider,
                        model,
                        attempt,
                        error,
                        duration_seconds,
                        int(retryable),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()

    def list_usage(self, limit: int = 100) -> list[dict]:
        """Return recent usage rows, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, provider, model, input_tokens, output_tokens, "
                "total_tokens FROM llm_usage ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, int]:
        """Aggregate request and token counts."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS requests, "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
                "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "COALESCE(SUM(total_tokens), 0) AS total_tokens "
                "FROM llm_usage"
            ).fetchone()
        return dict(row)

    def list_attempts(self, limit: int = 100) -> list[dict]:
        """Return recent failed attempts, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, provider, model, attempt, error, "
                "duration_seconds, retryable FROM llm_attempts "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_recorder: LLMUsageRecorder | None = None


def get_usage_recorder() -> LLMUsageRecorder:
    global _recorder
    if _recorder is None:
        _recorder = LLMUsageRecorder()
    return _recorder

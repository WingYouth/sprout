"""SQLite-backed agent step recorder.

Steps are part of the runtime-coordination authority (``sprout_core.db``),
which owns workspaces, tasks, runs and steps. They are *not* a private side
database: the recorder goes through the shared :class:`SqliteDatabase` driver
so pragmas, locking and connection pooling match every other authority.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from Sprout.storage.local.sqlite.driver import SqliteDatabase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    step INTEGER NOT NULL,
    content TEXT,
    tool_calls_json TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL
);
"""

_DEFAULT_PATH = Path.home() / ".sprout" / "data" / "sprout_core.db"


class AgentStepStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or _DEFAULT_PATH)
        self._db = SqliteDatabase.open(self._path)
        self._db.executescript(_SCHEMA)

    def record(
        self,
        *,
        session_id: str | None,
        step: int,
        content: str | None,
        tool_calls,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        calls = [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in tool_calls
        ]
        self._db.execute_sync(
            "INSERT INTO agent_steps "
            "(ts, session_id, step, content, tool_calls_json, prompt_tokens, "
            "completion_tokens, total_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                session_id,
                step,
                content,
                json.dumps(calls, ensure_ascii=False),
                prompt_tokens,
                completion_tokens,
                total_tokens,
            ),
        )

    def close(self) -> None:
        self._db.close()


_store: AgentStepStore | None = None


def get_agent_step_store() -> AgentStepStore:
    global _store
    if _store is None:
        _store = AgentStepStore()
    return _store

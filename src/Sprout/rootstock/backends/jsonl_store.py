"""JSONL session store: append-only, human-readable, git-friendly.

Each line is one JSON object tagged with ``kind`` — ``session`` or ``turn``.
The file is replayed on open (later records win), which keeps the write path
a single append and the format inspectable with any text tool.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from Sprout.rootstock.contract import blob_uris_in, turn_from_document, turn_to_document
from Sprout.session.models import Session, Turn


def _session_to_record(session: Session) -> dict[str, Any]:
    return {
        "kind": "session",
        "id": session.id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat(),
        "metadata": session.metadata,
    }


def _turn_to_record(turn: Turn) -> dict[str, Any]:
    return turn_to_document(turn)


def _append_line_sync(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


class JsonlSessionStore:
    """Sessions and turns appended to one ``.jsonl`` file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._turns: list[Turn] = []
        # Per-session high-water mark of ``seq``; rebuilt during replay so
        # post-restart appends keep the monotonic sequence going.
        self._seq_high_water: dict[str, int] = {}
        self._replay()

    def _replay(self) -> None:
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record["kind"] == "session":
                self._sessions[record["id"]] = Session(
                    id=record["id"],
                    user_id=record["user_id"],
                    created_at=datetime.fromisoformat(record["created_at"]),
                    metadata=record.get("metadata", {}),
                )
            elif record["kind"] == "turn":
                # Legacy records predate ``seq`` (they replay as 0, and new
                # appends continue from the high-water mark) and predate the
                # message-authority columns (they load at their defaults).
                seq = int(record.get("seq", 0))
                self._turns.append(turn_from_document(record))
                high = self._seq_high_water.get(record["session_id"], 0)
                if seq > high:
                    self._seq_high_water[record["session_id"]] = seq

    async def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        await asyncio.to_thread(_append_line_sync, self._path, line)

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def save_session(self, session: Session) -> None:
        self._sessions[session.id] = session
        await self._write(_session_to_record(session))

    async def append_turn(self, turn: Turn) -> None:
        # Assign a per-session monotonic seq when the caller did not, matching
        # the SQLite and in-memory backends' ordering guarantees.
        if turn.seq <= 0:
            high = self._seq_high_water.get(turn.session_id, 0) + 1
            turn = replace(turn, seq=high)
        self._seq_high_water[turn.session_id] = max(
            turn.seq, self._seq_high_water.get(turn.session_id, 0)
        )
        self._turns.append(turn)
        await self._write(_turn_to_record(turn))

    async def recent_turns(
        self, session_id: str, limit: int = 20
    ) -> Sequence[Turn]:
        session_turns = [turn for turn in self._turns if turn.session_id == session_id]
        session_turns.sort(key=lambda turn: turn.seq)
        return session_turns[-limit:]

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> Sequence[Turn]:
        filtered = [t for t in self._turns if t.session_id == session_id and t.seq < seq]
        filtered.sort(key=lambda t: t.seq)
        return filtered[-limit:]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(
            turn for turn in self._turns if turn.session_id == session_id
        )

    async def delete_session(self, session_id: str) -> int:
        before = sum(1 for t in self._turns if t.session_id == session_id)
        self._turns = [t for t in self._turns if t.session_id != session_id]
        self._sessions.pop(session_id, None)
        self._seq_high_water.pop(session_id, None)
        # Rewrite the JSONL file: drop the session and its turns.
        survivors = []
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                kind = record.get("kind")
                if kind == "session" and record.get("id") == session_id:
                    continue
                if kind == "turn" and record.get("session_id") == session_id:
                    continue
                survivors.append(line)
        with self._path.open("w", encoding="utf-8") as handle:
            for line in survivors:
                handle.write(line + "\n")
        return before

    async def count_sessions(self) -> int:
        return len(self._sessions)

    async def count_turns(self) -> int:
        return len(self._turns)

"""In-memory session store: the ephemeral fallback for tests and demos."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import replace

from Sprout.rootstock.contract import blob_uris_in
from Sprout.session.models import Session, Turn


class MemorySessionStore:
    """Keeps sessions and turns in process memory; nothing touches disk."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._turns: list[Turn] = []
        self._counters: dict[str, itertools.count] = {}

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def save_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    async def append_turn(self, turn: Turn) -> None:
        # Assign a per-session monotonic seq when the caller did not, so the
        # in-memory store matches the SQLite backend's ordering guarantees.
        if turn.seq <= 0:
            counter = self._counters.setdefault(
                turn.session_id, itertools.count(1)
            )
            turn = replace(turn, seq=next(counter))
        self._turns.append(turn)

    async def recent_turns(
        self, session_id: str, limit: int = 20
    ) -> Sequence[Turn]:
        session_turns = [t for t in self._turns if t.session_id == session_id]
        session_turns.sort(key=lambda t: t.seq)
        return session_turns[-limit:]

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> Sequence[Turn]:
        session_turns = [
            t for t in self._turns if t.session_id == session_id and t.seq < seq
        ]
        session_turns.sort(key=lambda t: t.seq)
        return session_turns[-limit:]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(
            turn for turn in self._turns if turn.session_id == session_id
        )

    async def delete_session(self, session_id: str) -> int:
        before = sum(1 for t in self._turns if t.session_id == session_id)
        self._turns = [t for t in self._turns if t.session_id != session_id]
        self._sessions.pop(session_id, None)
        self._counters.pop(session_id, None)
        return before

    async def count_sessions(self) -> int:
        return len(self._sessions)

    async def count_turns(self) -> int:
        return len(self._turns)
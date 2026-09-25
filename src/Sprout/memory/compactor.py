"""Session compactor: roll old turns into a digest, or split a session at a task boundary.

Rolling summary (M8 — Task 内部超长):

    S(n) = summarize(S(n-1), 新增 turns)

The key property is *only-append*: ``covered_through`` advances monotonically;
no summary is ever re-edited. The compactor costs O(new turns), not O(total).

Session split (M8 — Task 边界):

    child_session = next sibling
    parent_session_id = current.id

The split is a session-boundary event: ``ContextComposer`` must reload its
frozen snapshot at the new session (C4).
"""

from __future__ import annotations

from collections.abc import Sequence as _Seq
from datetime import datetime
from typing import Protocol

from Sprout.memory.contract import MemoryStore
from Sprout.memory.models import SessionSummary
from Sprout.rootstock.contract import SessionStore
from Sprout.session.models import Session, Turn
from Sprout.storage.local.sqlite.driver import SqliteDatabase


class Summarizer(Protocol):
    """A pluggable summarizer (LLM, offline heuristic)."""
    async def summarize(self, prior: str, additions: _Seq[Turn]) -> str: ...


class HeuristicSummarizer:
    """Offline fallback: take the conclusion lines of every added turn.

    Used when no ``compact_model`` is configured or the LLM call fails.
    """

    async def summarize(self, prior: str, additions: _Seq[Turn]) -> str:
        lines: list[str] = []
        if prior:
            lines.append(prior.rstrip())
        for turn in additions:
            tail = _tail_sentences(turn.content, max_chars=200)
            lines.append(f"- ({turn.role}, seq {turn.seq}) {tail}")
        return "\n".join(lines)


def _tail_sentences(text: str, *, max_chars: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return "…" + text[-max_chars:]


class SessionCompactor:
    """Drive the rolling summary and the Task-boundary split."""

    def __init__(
        self,
        session_store: SessionStore,
        memory_store: MemoryStore,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._sessions = session_store
        self._memory = memory_store
        self._summarizer = summarizer or HeuristicSummarizer()

    async def roll(self, session_id: str, threshold_seq: int) -> SessionSummary | None:
        latest = await self._memory.latest_session_summary(session_id)
        covered = latest.covered_through if latest else 0
        if threshold_seq <= covered:
            return None
        additions = await self._sessions.turns_before(
            session_id, seq=threshold_seq + 1, limit=200
        )
        additions = [t for t in additions if t.seq > covered]
        if not additions:
            return None
        prior = latest.content if latest else ""
        text = await self._summarizer.summarize(prior, additions)
        new_seq = latest.seq + 1 if latest else 1
        summary = SessionSummary(
            session_id=session_id,
            seq=new_seq,
            covered_through=additions[-1].seq,
            content=text,
        )
        await self._memory.save_session_summary(summary)
        await self._sync_session_summary(session_id, text)
        return summary

    async def _sync_session_summary(self, session_id: str, text: str) -> None:
        """Mirror the newest digest onto the ``sessions.summary`` column.

        The rolling history lives in the memory layer; the session row keeps
        only the latest digest so list/detail views can render it without a
        join (the column would otherwise stay empty — see DB-03).
        """
        session = await self._sessions.get_session(session_id)
        if session is None:
            return
        session.summary = text
        await self._sessions.save_session(session)

    async def split(
        self, parent: Session, *, new_user_id: str | None = None
    ) -> Session:
        """Fork ``parent`` into a new session; the child sees the parent's last summary."""
        child = Session(
            id=parent.id + "-child",
            user_id=new_user_id or parent.user_id,
            metadata={
                "parent_session_id": parent.id,
                "split_at": datetime.now().isoformat(),
            },
        )
        await self._sessions.save_session(child)
        return child


__all__ = ["SessionCompactor", "HeuristicSummarizer", "Summarizer"]


# ``SqliteDatabase`` re-export kept for legacy imports; not used in this module.
_ = SqliteDatabase  # noqa: F841
"""Memory layer data models.

Two layers of curated memory (Hermes 14.1):

- ``SessionFact`` / ``UserFact`` — small, hard-capped, hand-curated knowledge.
- ``SessionSummary`` — rolling digest of a session, monotonic and append-only.

Plus ``ContextMemory``: the read-only projection the model actually sees.
"""

from __future__ import annotations

from collections.abc import Sequence as _Seq
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from Sprout.session.models import Session, Turn
from Sprout.storage.contracts.knowledge import KnowledgeItem


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """One rolling snapshot of a session's state."""

    session_id: str
    seq: int  # monotonic per session; first summary is 1
    covered_through: int  # the highest turn.seq covered
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SessionFact:
    """A curated fact scoped to a single session."""

    session_id: str
    key: str
    value: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class UserFact:
    """A curated fact scoped to one user; survives session deletion."""

    user_id: str
    key: str
    value: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One match returned by full-text search over turns."""

    session_id: str
    turn_seq: int
    turn_id: str
    snippet: str
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class ContextMemory:
    """The read-only memory projection given to a model for one turn.

    Iteration over ``working`` yields :class:`Turn` rows; iteration over the
    whole object yields ``working`` then ``recalled`` so downstream code can
    treat ``ContextMemory`` as a drop-in for the previous ``Sequence[Turn]``.
    """

    session: Session
    working: tuple[Turn, ...] = ()
    summary: SessionSummary | None = None
    recalled: tuple[SearchHit, ...] = ()
    knowledge: tuple[KnowledgeItem, ...] = ()
    facts: tuple[SessionFact | UserFact, ...] = ()

    def __iter__(self) -> _Seq[Turn | SearchHit | KnowledgeItem | SessionFact | UserFact]:  # type: ignore[override]
        return iter(self.working)

    def __len__(self) -> int:
        return len(self.working)

    def __getitem__(self, index: int) -> Turn:
        return self.working[index]

    @property
    def metadata(self) -> dict[str, Any]:
        """Snapshot of non-turn parts for the system prompt wrapper."""
        return {
            "summary": self.summary.content if self.summary else None,
            "facts": [fact.value for fact in self.facts],
            "recalled_count": len(self.recalled),
            "knowledge_count": len(self.knowledge),
        }
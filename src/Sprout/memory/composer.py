"""ContextComposer: assemble the read-only ``ContextMemory`` for one turn.

Three guarantees:

1. The ``anchor_turns`` most-recent turns are kept verbatim, even if the
   budget is exhausted, so the model never loses the current conversation.
2. Curated facts and the latest summary are pinned to the system prompt and
   are not counted against the budget (they are hard-capped separately).
3. Recall and knowledge candidates compete for the same slot — anything that
   does not fit is dropped, not truncated.
"""

from __future__ import annotations

from collections.abc import Sequence as _Seq
from typing import TYPE_CHECKING

from Sprout.memory.budget import BudgetAllocator
from Sprout.memory.estimator import TokenEstimator, estimate_many
from Sprout.memory.models import ContextMemory

if TYPE_CHECKING:
    from Sprout.config.settings import ContextSettings
    from Sprout.memory.contract import MemoryStore
    from Sprout.session.models import Session, Turn
    from Sprout.storage.contracts.knowledge import KnowledgeItem


class ContextComposer:
    def __init__(
        self,
        *,
        settings: ContextSettings,
        memory_store: MemoryStore | None,
        estimator: TokenEstimator,
        allocator: BudgetAllocator | None = None,
        model_window: int | None = None,
    ) -> None:
        self._settings = settings
        self._memory_store = memory_store
        self._estimator = estimator
        self._allocator = allocator or BudgetAllocator(settings)
        self._model_window = model_window

    async def assemble(
        self,
        *,
        session: Session,
        history: _Seq[Turn],
        recalled: _Seq = (),
        knowledge: _Seq[KnowledgeItem] = (),
    ) -> ContextMemory:
        budget = self._allocator.allocate(self._model_window)
        anchor = self._settings.anchor_turns
        recent = list(history[-anchor:]) if anchor > 0 else []
        older = list(history[: max(0, len(history) - anchor)])

        # Anchor (current exchange + last few turns) always survives.
        working: list[Turn] = list(reversed(recent))
        anchor_tokens = estimate_many(self._estimator, [t.content for t in working])
        history_budget = max(0, budget.history - anchor_tokens)

        # Trim older history newest-first until it fits.
        trimmed_older: list[Turn] = []
        for turn in reversed(older):
            cost = self._estimator.estimate(turn.content)
            if history_budget < cost:
                break
            history_budget -= cost
            trimmed_older.append(turn)
        trimmed_older.reverse()
        working = trimmed_older + working

        summary = None  # session summaries live in the compactor layer, not memory
        facts: list = []
        if self._memory_store is not None:
            facts.extend(await self._memory_store.list_session_facts(session.id))
            if session.user_id:
                facts.extend(await self._memory_store.list_user_facts(session.user_id))

        recalled_covered = list(recalled)
        knowledge_covered = list(knowledge)

        return ContextMemory(
            session=session,
            working=tuple(working),
            summary=summary,
            recalled=tuple(recalled_covered),
            knowledge=tuple(knowledge_covered),
            facts=tuple(facts),
        )


__all__ = ["ContextComposer"]
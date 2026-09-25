"""Context budget allocation: split one turn's tokens by lane.

Hard caps (system prompt, tool schemas, character limits on curated facts)
are not part of the budget; soft ratios split the remainder. The allocator
is deterministic given the model window, so a planner can sanity-check a
turn's distribution in tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from Sprout.config.settings import ContextSettings


@dataclass(frozen=True, slots=True)
class Budget:
    """The split a single turn may spend on each context lane (in tokens)."""

    total: int
    summary: int
    history: int
    recalled: int
    knowledge: int
    skills: int
    completion: int

    def as_dict(self) -> Mapping[str, int]:
        return {
            "summary": self.summary,
            "history": self.history,
            "recalled": self.recalled,
            "knowledge": self.knowledge,
            "skills": self.skills,
            "completion": self.completion,
        }


class BudgetAllocator:
    """Turn soft-budget given the model window and the ContextSettings ratios."""

    def __init__(self, settings: ContextSettings) -> None:
        self._settings = settings

    def allocate(self, model_window: int | None = None) -> Budget:
        cfg = self._settings
        window = cfg.token_budget if cfg.token_budget > 0 else int(
            (model_window or 8000) * 0.75
        )
        ratios = {
            "summary": cfg.summary_ratio,
            "history": cfg.history_ratio,
            "recalled": cfg.recalled_ratio,
            "knowledge": cfg.knowledge_ratio,
            "skills": cfg.skills_ratio,
            "completion": cfg.completion_ratio,
        }
        allocated = {
            name: int(window * ratio) for name, ratio in ratios.items()
        }
        return Budget(
            total=window,
            summary=allocated["summary"],
            history=allocated["history"],
            recalled=allocated["recalled"],
            knowledge=allocated["knowledge"],
            skills=allocated["skills"],
            completion=allocated["completion"],
        )


__all__ = ["Budget", "BudgetAllocator"]
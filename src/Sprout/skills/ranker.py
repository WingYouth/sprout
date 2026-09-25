"""Ranking remote candidates, preferring ones that ship an install command (§7.5).

:class:`~Sprout.skills.matcher.SkillMatcher` scores *installed* skills against a
query. This module scores the *uninstalled* candidates a source returned, where
the deciding factor is different: a candidate with a copy-pasteable install
command can be set up reliably, while one that merely declares an unsatisfied
external CLI cannot run at all on this machine.

The score is a tie-breaker layered on top of the matcher's relevance score, not
a replacement: a barely-relevant skill with an install command must not outrank
an exact match. Callers pass the relevance through as ``relevance``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.skills.sources.base import SkillStub

#: Weights, kept as module constants so the ordering is auditable and testable.
W_INSTALL_COMMAND = 5.0
W_CLI_READY = 2.0
W_CLI_MISSING = -3.0


@dataclass(frozen=True, slots=True)
class RankedStub:
    """A candidate with its score and the reasons behind it."""

    stub: SkillStub
    score: float
    reasons: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.stub.name


def which(binary: str) -> str | None:
    """Indirection over :func:`shutil.which` so tests can stub the machine."""
    return shutil.which(binary)


def missing_cli(stub: SkillStub) -> tuple[str, ...]:
    """Declared external CLIs that are *not* available on this machine."""
    return tuple(binary for binary in stub.requires_cli if not which(binary))


def score_stub(stub: SkillStub, *, relevance: float = 0.0) -> RankedStub:
    """Score one candidate; higher is better.

    ``relevance`` is the source/matcher score the caller already computed, so
    this only contributes the distribution-quality signals on top of it.
    """
    score = relevance
    reasons: list[str] = []

    if stub.install_command:
        score += W_INSTALL_COMMAND
        reasons.append("has install command")

    if stub.requires_cli:
        missing = missing_cli(stub)
        if missing:
            score += W_CLI_MISSING
            reasons.append("missing CLI: " + ", ".join(missing))
        else:
            score += W_CLI_READY
            reasons.append("external CLI available")

    return RankedStub(stub=stub, score=score, reasons=tuple(reasons))


def rank_stubs(
    candidates: list[tuple[SkillStub, float]], *, limit: int
) -> list[RankedStub]:
    """Rank ``(stub, relevance)`` pairs, best first, then dedupe by name."""
    ranked = [score_stub(stub, relevance=relevance) for stub, relevance in candidates]
    ranked.sort(key=lambda item: (-item.score, item.stub.name))

    seen: set[str] = set()
    unique: list[RankedStub] = []
    for item in ranked:
        if item.stub.name in seen:
            continue
        seen.add(item.stub.name)
        unique.append(item)
    return unique[:limit]

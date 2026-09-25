"""Growth signals: evidence-backed observations that something should change."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from Sprout.evolution.models.evidence import EvidenceRef


class SignalType:
    """Well-known signal types; free-form strings are allowed."""

    REPEATED_FAILURE = "repeated_failure"
    KNOWLEDGE_GAP = "knowledge_gap"
    SKILL_GAP = "skill_gap"
    SKILL_IMPROVEMENT = "skill_improvement"
    BEHAVIOR_PATTERN = "behavior_pattern"


@dataclass(frozen=True, slots=True)
class GrowthSignal:
    """A signal must reference evidence and keep its scores in [0, 1]."""

    type: str
    title: str
    description: str
    evidence: tuple[EvidenceRef, ...]
    confidence: float
    impact_score: float
    recurrence_score: float
    severity_score: float
    id: str = field(default_factory=lambda: str(uuid4()))
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("A growth signal must reference evidence")
        if not self.title.strip():
            raise ValueError("A growth signal must have a title")
        for name in ("confidence", "impact_score", "recurrence_score", "severity_score"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

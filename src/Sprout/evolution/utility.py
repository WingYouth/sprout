"""Simple utility scoring for growth candidates."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.artifacts.models import ArtifactKind, GrowthCandidate


@dataclass(frozen=True, slots=True)
class UtilityReport:
    score: float
    notes: tuple[str, ...] = ()


class UtilityEvaluator:
    """Ranks candidates before they reach human approval."""

    def evaluate(self, candidate: GrowthCandidate) -> UtilityReport:
        notes: list[str] = []
        score = 0.0
        if candidate.evidence_ids:
            score += min(0.4, 0.1 * len(candidate.evidence_ids))
            notes.append("evidence present")
        if candidate.artifact is not None:
            if len(candidate.artifact.content.strip()) >= 80:
                score += 0.2
                notes.append("substantial content")
            if candidate.artifact.kind in {ArtifactKind.SKILL, ArtifactKind.PROJECT_KNOWLEDGE}:
                score += 0.2
                notes.append("high-value artifact kind")
            if candidate.artifact.status.value == "candidate":
                score += 0.1
        if candidate.diagnosis:
            score += 0.1
            notes.append("diagnosis present")
        return UtilityReport(score=min(1.0, score), notes=tuple(notes))

"""Build versioned growth candidates from signals."""

from __future__ import annotations

import re

from Sprout.artifacts.models import Artifact, ArtifactStatus, GrowthCandidate
from Sprout.evolution.growth_router import GrowthRouter, RoutingDecision
from Sprout.evolution.models.signals import GrowthSignal

_SLUG = re.compile(r"[^a-z0-9]+")


class GrowthCandidateBuilder:
    """Bridges legacy GrowthSignal objects into the new Artifact model."""

    def __init__(self, router: GrowthRouter | None = None) -> None:
        self._router = router or GrowthRouter()

    def build(self, signal: GrowthSignal) -> GrowthCandidate:
        decision = self._router.route(signal)
        artifact = Artifact(
            kind=decision.artifact_kind,
            name=self._slug(signal.title),
            version="0.1.0",
            content=self._content(signal, decision),
            status=ArtifactStatus.CANDIDATE,
            scope=decision.scope,
            evidence_ids=tuple(ref.source_id for ref in signal.evidence),
            metadata={
                "diagnosis": signal.description,
                "rationale": decision.rationale,
            },
        )
        return GrowthCandidate(
            artifact=artifact,
            evidence_ids=tuple(ref.source_id for ref in signal.evidence),
            diagnosis=signal.description,
            rationale=decision.rationale,
        )

    @staticmethod
    def _content(signal: GrowthSignal, decision: RoutingDecision) -> str:
        return f"{signal.title}\n\n{signal.description}\n\nTarget: {decision.artifact_kind.value}"

    @staticmethod
    def _slug(text: str) -> str:
        return _SLUG.sub("-", text.casefold()).strip("-") or "candidate"

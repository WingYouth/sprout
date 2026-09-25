"""Growth routing from signals to artifact kinds."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.artifacts.models import ArtifactKind
from Sprout.evolution.models.signals import GrowthSignal


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    artifact_kind: ArtifactKind
    scope: str = "workspace"
    rationale: str = ""


class GrowthRouter:
    """Chooses which externalized artifact should be created or updated."""

    def route(self, signal: GrowthSignal) -> RoutingDecision:
        kind = {
            "repeated_failure": ArtifactKind.SKILL,
            "skill_gap": ArtifactKind.SKILL,
            "skill_improvement": ArtifactKind.SKILL,
            "knowledge_gap": ArtifactKind.PROJECT_KNOWLEDGE,
            "behavior_pattern": ArtifactKind.WORKFLOW,
        }.get(signal.type, ArtifactKind.PROJECT_KNOWLEDGE)
        return RoutingDecision(
            artifact_kind=kind,
            scope="workspace",
            rationale=f"Signal type {signal.type} routes to {kind.value}",
        )

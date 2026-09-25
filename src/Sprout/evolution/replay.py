"""Replay case construction and candidate replay evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.artifacts.models import ArtifactKind, GrowthCandidate
from Sprout.evolution.hard_gate import GateChecks
from Sprout.trajectory.models import (
    ArtifactSnapshot,
    ReplayCase,
    Trajectory,
)


@dataclass(frozen=True, slots=True)
class ReplayReport:
    passed: bool
    score: float
    notes: tuple[str, ...] = ()


class ReplayCaseBuilder:
    """Builds a replay case from an immutable trajectory."""

    def build(
        self,
        trajectory: Trajectory,
        *,
        artifact_snapshot: ArtifactSnapshot | None = None,
        fixed_scope: tuple[str, ...] = (),
    ) -> ReplayCase:
        return ReplayCase(
            trajectory_id=trajectory.id,
            workspace_revision=trajectory.workspace_revision,
            artifact_snapshot=artifact_snapshot,
            fixed_scope=fixed_scope,
        )


class ReplayEvaluator:
    """Rule-based replay gate.

    This is the first replay implementation. It validates that candidate
    evidence comes from the trajectory and that the artifact addresses a
    failure or knowledge gap. A real sandbox replay can replace this later.
    """

    def __init__(self, *, threshold: float = 0.6) -> None:
        self._threshold = threshold

    def evaluate(
        self,
        candidate: GrowthCandidate,
        replay_case: ReplayCase,
        trajectory: Trajectory,
    ) -> ReplayReport:
        notes: list[str] = []
        score = 0.0
        event_ids = {event.id for event in trajectory.events}

        evidence_present = bool(candidate.evidence_ids)
        if evidence_present and all(item in event_ids for item in candidate.evidence_ids):
            score += 0.4
            notes.append("candidate evidence matches trajectory")

        failed = any(event.name in {"node.failed", "task.failed"} for event in trajectory.events)
        if failed and candidate.artifact is not None:
            score += 0.2
            notes.append("candidate addresses a failed trajectory")

        if candidate.artifact is not None:
            if len(candidate.artifact.content.strip()) >= 80:
                score += 0.2
                notes.append("substantial artifact content")
            if candidate.artifact.kind in {ArtifactKind.SKILL, ArtifactKind.PROJECT_KNOWLEDGE}:
                score += 0.1
                notes.append("high-value artifact kind")
            if candidate.artifact.scope == "workspace":
                score += 0.1
                notes.append("workspace-scoped change")

        score = min(1.0, score)
        return ReplayReport(
            passed=score >= self._threshold and evidence_present,
            score=round(score, 2),
            notes=tuple(notes),
        )

    @staticmethod
    def checks(trajectory: Trajectory) -> GateChecks:
        """Turn replay-time test and regression signals into hard-gate inputs."""
        names = {event.name for event in trajectory.events}
        tests_passed: bool | None = None
        if any(name.startswith("test.") for name in names):
            tests_passed = not bool(names & {"test.failed", "evaluation.failed"})
        regression_free: bool | None = None
        if names & {"regression.detected", "rollback.failed"}:
            regression_free = False
        return GateChecks(tests_passed=tests_passed, regression_free=regression_free)

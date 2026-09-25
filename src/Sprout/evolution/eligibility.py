"""Trajectory eligibility filtering for growth."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.trajectory.models import Trajectory, TrajectoryStatus

_BLOCKED_EVENTS = {
    "task.cancelled",
    "user.cancelled",
    "approval.rejected",
    "secret.leak",
}

_MEANINGFUL_EVENTS = {
    "agent.completed",
    "agent.failed",
    "tool.completed",
    "tool.failed",
    "node.completed",
    "node.failed",
    "sandbox.applied",
    "task.completed",
    "task.failed",
}


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason: str


class LearningEligibilityFilter:
    """Decides whether a trajectory is safe and useful as growth evidence."""

    def evaluate(self, trajectory: Trajectory) -> EligibilityDecision:
        if not trajectory.events:
            return EligibilityDecision(False, "Trajectory has no events")

        names = {event.name for event in trajectory.events}
        if names.intersection(_BLOCKED_EVENTS):
            return EligibilityDecision(False, "Trajectory contains a blocked event")
        if not names.intersection(_MEANINGFUL_EVENTS):
            return EligibilityDecision(False, "Trajectory has no meaningful execution events")
        if trajectory.status is TrajectoryStatus.RECORDING:
            return EligibilityDecision(False, "Trajectory is still recording")
        return EligibilityDecision(True, "eligible")

"""Centralized state transition rules."""

from __future__ import annotations

from Sprout.artifacts.models import ArtifactStatus
from Sprout.execution.models import ChangeProposalStatus
from Sprout.orchestration.models import NodeStatus
from Sprout.task.models import TaskStatus


class TaskStateMachine:
    transitions: dict[TaskStatus, frozenset[TaskStatus]] = {
        TaskStatus.CREATED: frozenset(
            {
                TaskStatus.DISCOVERING,
                TaskStatus.PLANNING,
                TaskStatus.READY,
                TaskStatus.RUNNING,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.DISCOVERING: frozenset({TaskStatus.PLANNING, TaskStatus.FAILED}),
        TaskStatus.PLANNING: frozenset({TaskStatus.READY, TaskStatus.FAILED}),
        TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.WAITING_RESOURCE,
                TaskStatus.RETRYING,
                TaskStatus.PAUSED,
                TaskStatus.EVALUATING,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.WAITING_APPROVAL: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.WAITING_RESOURCE: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.RETRYING: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
        TaskStatus.PAUSED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.EVALUATING: frozenset(
            {TaskStatus.READY_TO_APPLY, TaskStatus.FAILED}
        ),
        TaskStatus.READY_TO_APPLY: frozenset({TaskStatus.APPLYING, TaskStatus.FAILED}),
        TaskStatus.APPLYING: frozenset(
            {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ROLLED_BACK}
        ),
        TaskStatus.COMPLETED: frozenset(),
        TaskStatus.FAILED: frozenset({TaskStatus.RETRYING, TaskStatus.CANCELLED}),
        TaskStatus.CANCELLED: frozenset(),
        TaskStatus.ROLLED_BACK: frozenset(),
    }

    @classmethod
    def can_transition(cls, current: TaskStatus, target: TaskStatus) -> bool:
        return target in cls.transitions.get(current, frozenset())

    @classmethod
    def validate(cls, current: TaskStatus, target: TaskStatus) -> None:
        if not cls.can_transition(current, target):
            raise ValueError(f"Invalid task transition: {current.value} -> {target.value}")


class NodeStateMachine:
    transitions: dict[NodeStatus, frozenset[NodeStatus]] = {
        NodeStatus.PENDING: frozenset(
            {
                NodeStatus.READY,
                NodeStatus.RUNNING,
                NodeStatus.FAILED,
                NodeStatus.SKIPPED,
                NodeStatus.CANCELLED,
            }
        ),
        NodeStatus.READY: frozenset({NodeStatus.RUNNING, NodeStatus.CANCELLED}),
        NodeStatus.RUNNING: frozenset(
            {
                NodeStatus.WAITING,
                NodeStatus.COMPLETED,
                NodeStatus.FAILED,
                NodeStatus.CANCELLED,
            }
        ),
        NodeStatus.WAITING: frozenset(
            {
                NodeStatus.READY,
                NodeStatus.RUNNING,
                NodeStatus.FAILED,
                NodeStatus.CANCELLED,
            }
        ),
        NodeStatus.COMPLETED: frozenset(),
        NodeStatus.FAILED: frozenset({NodeStatus.RUNNING, NodeStatus.CANCELLED}),
        NodeStatus.CANCELLED: frozenset(),
        NodeStatus.SKIPPED: frozenset(),
    }

    @classmethod
    def can_transition(cls, current: NodeStatus, target: NodeStatus) -> bool:
        return target in cls.transitions.get(current, frozenset())

    @classmethod
    def validate(cls, current: NodeStatus, target: NodeStatus) -> None:
        if not cls.can_transition(current, target):
            raise ValueError(f"Invalid node transition: {current.value} -> {target.value}")


class ArtifactStateMachine:
    transitions: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
        ArtifactStatus.DRAFT: frozenset(
            {ArtifactStatus.CANDIDATE, ArtifactStatus.REJECTED}
        ),
        ArtifactStatus.CANDIDATE: frozenset(
            {ArtifactStatus.VALIDATED, ArtifactStatus.REJECTED}
        ),
        ArtifactStatus.VALIDATED: frozenset(
            {ArtifactStatus.PENDING_APPROVAL, ArtifactStatus.PUBLISHED, ArtifactStatus.REJECTED}
        ),
        ArtifactStatus.PENDING_APPROVAL: frozenset(
            {ArtifactStatus.PUBLISHED, ArtifactStatus.REJECTED}
        ),
        ArtifactStatus.PUBLISHED: frozenset({ArtifactStatus.MONITORING}),
        ArtifactStatus.MONITORING: frozenset(
            {ArtifactStatus.STABLE, ArtifactStatus.DEPRECATED}
        ),
        ArtifactStatus.STABLE: frozenset({ArtifactStatus.DEPRECATED}),
        ArtifactStatus.DEPRECATED: frozenset(),
        ArtifactStatus.REJECTED: frozenset(),
        ArtifactStatus.ROLLED_BACK: frozenset(),
    }

    @classmethod
    def can_transition(cls, current: ArtifactStatus, target: ArtifactStatus) -> bool:
        return target in cls.transitions.get(current, frozenset())

    @classmethod
    def validate(cls, current: ArtifactStatus, target: ArtifactStatus) -> None:
        if not cls.can_transition(current, target):
            raise ValueError(f"Invalid artifact transition: {current.value} -> {target.value}")


class ChangeProposalStateMachine:
    transitions: dict[ChangeProposalStatus, frozenset[ChangeProposalStatus]] = {
        ChangeProposalStatus.PENDING: frozenset(
            {
                ChangeProposalStatus.APPROVED,
                ChangeProposalStatus.REJECTED,
            }
        ),
        ChangeProposalStatus.APPROVED: frozenset(
            {
                ChangeProposalStatus.APPLIED,
                ChangeProposalStatus.REJECTED,
            }
        ),
        ChangeProposalStatus.APPLIED: frozenset(
            {ChangeProposalStatus.ROLLED_BACK}
        ),
        ChangeProposalStatus.REJECTED: frozenset(),
        ChangeProposalStatus.ROLLED_BACK: frozenset(),
    }

    @classmethod
    def can_transition(
        cls,
        current: ChangeProposalStatus,
        target: ChangeProposalStatus,
    ) -> bool:
        return target in cls.transitions.get(current, frozenset())

    @classmethod
    def validate(
        cls,
        current: ChangeProposalStatus,
        target: ChangeProposalStatus,
    ) -> None:
        if not cls.can_transition(current, target):
            raise ValueError(
                f"Invalid change proposal transition: {current.value} -> {target.value}"
            )

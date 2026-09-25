"""Tests for runtime state machines."""

from __future__ import annotations

import pytest

from Sprout.orchestration.models import NodeStatus
from Sprout.runtime.state import NodeStateMachine, TaskStateMachine
from Sprout.task.models import TaskStatus


def test_task_state_machine_allows_valid_transitions() -> None:
    assert TaskStateMachine.can_transition(
        TaskStatus.CREATED,
        TaskStatus.RUNNING,
    )
    assert TaskStateMachine.can_transition(
        TaskStatus.RUNNING,
        TaskStatus.WAITING_APPROVAL,
    )


def test_task_state_machine_rejects_invalid_transitions() -> None:
    with pytest.raises(ValueError):
        TaskStateMachine.validate(
            TaskStatus.COMPLETED,
            TaskStatus.RUNNING,
        )


def test_node_state_machine_allows_running_to_completed() -> None:
    NodeStateMachine.validate(NodeStatus.RUNNING, NodeStatus.COMPLETED)

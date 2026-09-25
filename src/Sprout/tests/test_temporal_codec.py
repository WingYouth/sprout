"""Tests for the JSON-safe Temporal orchestration codec."""

from __future__ import annotations

from Sprout.orchestration.models import ExecutionGraph, ExecutionNode, NodeType
from Sprout.orchestration.temporal_codec import (
    graph_to_dict,
    node_from_dict,
    node_to_dict,
)
from Sprout.orchestration.temporal_workflows import _skip_verify_loop


def test_node_codec_round_trips_datetimes() -> None:
    node = ExecutionNode(task_id="task-1", type=NodeType.READ)

    payload = node_to_dict(node)
    assert isinstance(payload["created_at"], str)

    restored = node_from_dict(payload)
    assert restored.id == node.id
    assert restored.task_id == node.task_id
    assert restored.type is NodeType.READ
    assert restored.created_at == node.created_at


def test_graph_codec_encodes_every_node() -> None:
    graph = ExecutionGraph(
        task_id="task-1",
        nodes=(
            ExecutionNode(task_id="task-1", type=NodeType.READ),
            ExecutionNode(task_id="task-1", type=NodeType.APPLY),
        ),
    )

    payload = graph_to_dict(graph)
    assert payload["task_id"] == "task-1"
    assert len(payload["nodes"]) == 2
    assert all(isinstance(item["created_at"], str) for item in payload["nodes"])


def test_temporal_workflow_skips_remaining_verify_nodes() -> None:
    nodes = [
        {"id": "evaluation", "type": "evaluation"},
        {"id": "agent:1", "type": "agent"},
        {"id": "evaluation:1", "type": "evaluation"},
        {"id": "approval", "type": "approval"},
        {"id": "apply", "type": "apply"},
    ]
    results: list[dict] = []

    next_index = _skip_verify_loop(nodes, 1, results)

    assert next_index == 3
    assert results == [
        {"node_id": "agent:1", "status": "skipped", "skipped": True},
        {"node_id": "evaluation:1", "status": "skipped", "skipped": True},
    ]

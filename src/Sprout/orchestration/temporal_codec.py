"""JSON-safe codec for orchestration models crossing the Temporal boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from Sprout.orchestration.models import (
    DataRef,
    ExecutionGraph,
    ExecutionNode,
    NodeBudget,
    NodeStatus,
    NodeType,
)


def _budget_to_dict(budget: NodeBudget) -> dict[str, Any]:
    return {
        "max_attempts": budget.max_attempts,
        "timeout_seconds": budget.timeout_seconds,
        "max_tokens": budget.max_tokens,
    }


def _budget_from_dict(data: dict[str, Any]) -> NodeBudget:
    return NodeBudget(
        max_attempts=int(data.get("max_attempts", 1)),
        timeout_seconds=float(data.get("timeout_seconds", 0.0)),
        max_tokens=int(data.get("max_tokens", 0)),
    )


def node_to_dict(node: ExecutionNode) -> dict[str, Any]:
    """Encode one execution node without non-JSON types."""
    return {
        "id": node.id,
        "task_id": node.task_id,
        "type": node.type.value,
        "dependencies": list(node.dependencies),
        "status": node.status.value,
        "attempts": node.attempts,
        "budget": _budget_to_dict(node.budget),
        "result_ref": (
            {
                "id": node.result_ref.id,
                "store": node.result_ref.store,
                "key": node.result_ref.key,
                "content_hash": node.result_ref.content_hash,
            }
            if node.result_ref is not None
            else None
        ),
        "metadata": dict(node.metadata),
        "created_at": node.created_at.isoformat(),
    }


def node_from_dict(data: dict[str, Any]) -> ExecutionNode:
    """Decode one execution node encoded by :func:`node_to_dict`."""
    result_ref = data.get("result_ref")
    return ExecutionNode(
        id=str(data["id"]),
        task_id=str(data.get("task_id", "")),
        type=NodeType(data["type"]),
        dependencies=tuple(data.get("dependencies", ())),
        status=NodeStatus(data.get("status", "pending")),
        attempts=int(data.get("attempts", 0)),
        budget=_budget_from_dict(data.get("budget", {})),
        result_ref=(
            DataRef(
                id=str(result_ref["id"]),
                store=str(result_ref.get("store", "blob")),
                key=str(result_ref.get("key", "")),
                content_hash=(
                    str(result_ref["content_hash"])
                    if result_ref.get("content_hash") is not None
                    else None
                ),
            )
            if isinstance(result_ref, dict)
            else None
        ),
        metadata=dict(data.get("metadata", {})),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def graph_to_dict(graph: ExecutionGraph) -> dict[str, Any]:
    """Encode an execution graph without non-JSON types."""
    return {
        "task_id": graph.task_id,
        "nodes": [node_to_dict(node) for node in graph.nodes],
        "entry_node_ids": list(graph.entry_node_ids),
        "created_at": graph.created_at.isoformat(),
    }

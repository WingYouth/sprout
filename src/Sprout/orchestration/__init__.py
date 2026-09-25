"""Execution graph and node models.

The heavy graph compiler and sequential runner are imported lazily so that
importing a submodule such as ``temporal_workflows`` does not drag the LLM,
HTTP, and gateway dependency graph into Temporal's workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Sprout.orchestration.models import (
    DataRef,
    ExecutionGraph,
    ExecutionNode,
    NodeBudget,
    NodeStatus,
    NodeType,
)

if TYPE_CHECKING:
    from Sprout.orchestration.compiler import ExecutionGraphBuilder
    from Sprout.orchestration.service import NodeResult, SequentialOrchestrator

__all__ = [
    "DataRef",
    "ExecutionGraph",
    "ExecutionGraphBuilder",
    "ExecutionNode",
    "NodeBudget",
    "NodeStatus",
    "NodeType",
    "NodeResult",
    "SequentialOrchestrator",
]


def __getattr__(name: str):
    if name == "ExecutionGraphBuilder":
        from Sprout.orchestration.compiler import ExecutionGraphBuilder

        return ExecutionGraphBuilder
    if name in {"NodeResult", "SequentialOrchestrator"}:
        from Sprout.orchestration import service as _service

        return getattr(_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

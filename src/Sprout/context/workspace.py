"""Structured workspace context injected into AgentContext."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkspaceGraphNodeContext:
    id: str
    kind: str
    name: str
    qualified_name: str = ""
    line: int = 0
    granularity: str = "file"


@dataclass(frozen=True, slots=True)
class WorkspaceGraphEdgeContext:
    source: str
    target: str
    relation: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace_id: str
    summary: str = ""
    knowledge: tuple[str, ...] = ()
    graph_nodes: tuple[WorkspaceGraphNodeContext, ...] = ()
    graph_edges: tuple[WorkspaceGraphEdgeContext, ...] = ()
    stale_knowledge_ids: tuple[str, ...] = ()


__all__ = [
    "WorkspaceContext",
    "WorkspaceGraphEdgeContext",
    "WorkspaceGraphNodeContext",
]

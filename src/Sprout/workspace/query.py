"""Read-only query helpers over a WorkspaceAnalysis."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.workspace.intelligence import WorkspaceAnalysis


@dataclass(frozen=True, slots=True)
class WorkspaceQueryResult:
    nodes: tuple[object, ...] = ()
    edges: tuple[object, ...] = ()
    knowledge: tuple[object, ...] = ()


class WorkspaceQuery:
    """Query a workspace analysis without mutating any project data.

    Graph nodes carry the *absolute* resource path, because
    ``Runtime.open_workspace`` resolves the workspace root before the scanner
    walks it. A caller at a shell types a *workspace-relative* path instead, so
    every path-shaped lookup accepts both spellings rather than silently
    returning nothing for a file that plainly exists.
    """

    def __init__(self, analysis: WorkspaceAnalysis) -> None:
        self._analysis = analysis

    def _resource_key(self, path: str) -> str:
        """Canonical comparison key for a resource path.

        A relative path is resolved against the workspace root; both sides are
        then normalised for the host platform, so a Windows caller does not
        have to match the on-disk letter case by hand.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._analysis.workspace.root / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:  # pragma: no cover - pathological paths only
            resolved = candidate
        return os.path.normcase(resolved.as_posix())

    def _identity_ids(self, name: str) -> set[str]:
        """Node ids addressed by ``name``: id, name, qualified name, or path."""
        if not name:
            return set()
        key = self._resource_key(name)
        return {
            node.id
            for node in self._analysis.graph.nodes
            if name in {node.id, node.name, node.qualified_name}
            or (
                node.resource is not None
                and self._resource_key(node.resource.path) == key
            )
        }

    def neighbors(
        self,
        name: str,
        *,
        relation: str | None = None,
    ) -> WorkspaceQueryResult:
        graph = self._analysis.graph
        ids = self._identity_ids(name)
        edges = [
            edge
            for edge in graph.edges
            if edge.source in ids or edge.target in ids
        ]
        if relation:
            edges = [edge for edge in edges if edge.relation == relation]
        neighbor_ids = {
            edge.target if edge.source in ids else edge.source
            for edge in edges
        }
        nodes = [node for node in graph.nodes if node.id in neighbor_ids]
        return WorkspaceQueryResult(nodes=tuple(nodes), edges=tuple(edges))

    def symbols(
        self,
        *,
        kind: str | None = None,
        query: str = "",
    ) -> tuple[object, ...]:
        nodes = [
            node
            for node in self._analysis.graph.nodes
            if node.kind in {"class", "function", "method", "test"}
        ]
        if kind:
            nodes = [node for node in nodes if node.kind == kind]
        if query:
            lowered = query.casefold()
            nodes = [
                node
                for node in nodes
                if lowered in node.name.casefold()
                or lowered in node.qualified_name.casefold()
            ]
        return tuple(nodes)

    def dependencies(
        self,
        path: str,
        *,
        direction: str = "out",
    ) -> tuple[object, ...]:
        """Edges touching the resource at ``path``.

        ``path`` accepts the absolute resource path carried by the graph nodes
        as well as a path relative to the workspace root.
        """
        graph = self._analysis.graph
        key = self._resource_key(path)
        ids = {
            node.id
            for node in graph.nodes
            if node.resource is not None
            and self._resource_key(node.resource.path) == key
        }
        edges = []
        for edge in graph.edges:
            if direction == "out" and edge.source in ids:
                edges.append(edge)
            elif direction == "in" and edge.target in ids:
                edges.append(edge)
            elif direction == "both" and (edge.source in ids or edge.target in ids):
                edges.append(edge)
        return tuple(edges)

    def subgraph(
        self,
        name: str,
        *,
        max_depth: int = 2,
        relation: str | None = None,
    ) -> WorkspaceQueryResult:
        """Return nodes and edges within ``max_depth`` hops of a matching node."""
        graph = self._analysis.graph
        matched_ids = self._identity_ids(name)
        if not matched_ids:
            return WorkspaceQueryResult()

        node_ids = set(matched_ids)
        edge_set = set()
        frontier = set(matched_ids)

        for _ in range(max(1, max_depth)):
            next_frontier: set[str] = set()
            for edge in graph.edges:
                if relation and edge.relation != relation:
                    continue
                if edge.source in frontier or edge.target in frontier:
                    edge_set.add(edge)
                    if edge.source not in node_ids:
                        next_frontier.add(edge.source)
                    if edge.target not in node_ids:
                        next_frontier.add(edge.target)
            node_ids.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        return WorkspaceQueryResult(
            nodes=tuple(node for node in graph.nodes if node.id in node_ids),
            edges=tuple(sorted(edge_set, key=lambda edge: edge.id)),
        )

    def knowledge(
        self,
        query: str = "",
        *,
        kind: str | None = None,
    ) -> tuple[object, ...]:
        items = self._analysis.knowledge.items
        if kind:
            items = tuple(item for item in items if item.kind == kind)
        if query:
            lowered = query.casefold()
            items = tuple(
                item
                for item in items
                if lowered in item.statement.casefold()
            )
        return tuple(items)


__all__ = ["WorkspaceQuery", "WorkspaceQueryResult"]

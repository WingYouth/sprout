"""Read-only Agent tool for querying Workspace Intelligence."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec
from Sprout.workspace.intelligence import WorkspaceAnalysis


class WorkspaceQueryTool:
    """Low-risk tool exposing workspace graph, symbols, and knowledge queries."""

    def __init__(
        self,
        analyze: Callable[[str], Awaitable[WorkspaceAnalysis]],
    ) -> None:
        self._analyze = analyze
        self.spec = ToolSpec(
            name="workspace_query",
            description="Read-only queries over a project workspace graph, symbols, "
            "dependencies, and knowledge.",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "Workspace id to analyze.",
                    },
                    "operation": {
                        "type": "string",
                        "enum": [
                            "neighbors",
                            "subgraph",
                            "symbols",
                            "dependencies",
                            "knowledge",
                        ],
                        "description": "Query operation to run.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Node id, name, qualified name, or file path "
                        "for neighbors.",
                    },
                    "relation": {
                        "type": "string",
                        "description": "Optional edge relation filter.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Resource path for dependency queries, "
                        "workspace-relative or absolute.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["out", "in", "both"],
                        "description": "Dependency traversal direction.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Case-insensitive text filter.",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Symbol or knowledge kind filter.",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum subgraph traversal depth.",
                    },
                },
                "required": ["workspace_id", "operation"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        workspace_id = arguments.get("workspace_id")
        operation = arguments.get("operation")
        if not isinstance(workspace_id, str) or not workspace_id:
            return ToolResult.failure("Argument 'workspace_id' is required")
        if not isinstance(operation, str):
            return ToolResult.failure("Argument 'operation' is required")

        try:
            analysis = await self._analyze(workspace_id)
        except Exception as exc:
            return ToolResult.failure(f"Workspace query failed: {exc}")

        query = analysis.query()
        if operation == "neighbors":
            result = query.neighbors(
                str(arguments.get("name", "")),
                relation=self._optional_str(arguments, "relation"),
            )
            payload = {
                "nodes": [_node_dict(node) for node in result.nodes],
                "edges": [_edge_dict(edge) for edge in result.edges],
            }
        elif operation == "symbols":
            payload = [
                _node_dict(node)
                for node in query.symbols(
                    kind=self._optional_str(arguments, "kind"),
                    query=str(arguments.get("query", "")),
                )
            ]
        elif operation == "subgraph":
            max_depth = arguments.get("max_depth", 2)
            try:
                max_depth = int(max_depth)
            except (TypeError, ValueError):
                max_depth = 2
            result = query.subgraph(
                str(arguments.get("name", "")),
                max_depth=max_depth,
                relation=self._optional_str(arguments, "relation"),
            )
            payload = {
                "nodes": [_node_dict(node) for node in result.nodes],
                "edges": [_edge_dict(edge) for edge in result.edges],
            }
        elif operation == "dependencies":
            payload = [
                _edge_dict(edge)
                for edge in query.dependencies(
                    str(arguments.get("path", "")),
                    direction=str(arguments.get("direction", "out")),
                )
            ]
        elif operation == "knowledge":
            payload = [
                _knowledge_dict(item)
                for item in query.knowledge(
                    str(arguments.get("query", "")),
                    kind=self._optional_str(arguments, "kind"),
                )
            ]
        else:
            return ToolResult.failure(f"Unsupported operation: {operation}")

        return ToolResult.success(
            json.dumps(payload, ensure_ascii=False, indent=2),
            data=payload,
        )

    @staticmethod
    def _optional_str(
        arguments: Mapping[str, Any],
        key: str,
    ) -> str | None:
        value = arguments.get(key)
        return value if isinstance(value, str) and value else None


def _node_dict(node: Any) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "line": node.line,
        "granularity": node.granularity,
    }


def _edge_dict(edge: Any) -> dict[str, Any]:
    return {
        "source": edge.source,
        "target": edge.target,
        "relation": edge.relation,
        "confidence": edge.confidence,
    }


def _knowledge_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "statement": item.statement,
        "confidence": item.confidence,
        "evidence_ids": list(item.evidence_ids),
    }


__all__ = ["WorkspaceQueryTool"]

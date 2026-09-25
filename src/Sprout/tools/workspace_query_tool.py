"""Read-only Agent tool for querying Workspace Intelligence."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
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
                            "locate_feature",
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
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum feature location candidates to return.",
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
        elif operation == "locate_feature":
            feature_query = str(arguments.get("query", "")).strip()
            if not feature_query:
                return ToolResult.failure("Argument 'query' is required for locate_feature")
            max_results = arguments.get("max_results", 8)
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                max_results = 8
            payload = _feature_locations(
                analysis,
                feature_query,
                max_results=max(1, min(max_results, 25)),
            )
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
        "path": node.resource.path if node.resource is not None else "",
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


def _feature_locations(
    analysis: WorkspaceAnalysis,
    feature_query: str,
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    nodes = [
        node
        for node in analysis.graph.nodes
        if node.resource is not None
        and node.kind
        in {
            "class",
            "function",
            "method",
            "test",
            "component",
            "page",
            "route",
            "hook",
            "store",
            "api_route",
            "data_asset",
            "config_asset",
            "source",
        }
    ]
    knowledge_by_path = _knowledge_scores_by_path(analysis, feature_query)
    ranked = []
    for node in nodes:
        path = node.resource.path if node.resource is not None else ""
        score, reasons = _feature_score(feature_query, node, path)
        if path in knowledge_by_path:
            score += knowledge_by_path[path]
            reasons.append("knowledge")
        if score <= 0:
            continue
        location = _node_location(analysis, node)
        ranked.append(
            {
                "score": round(score, 3),
                "reasons": reasons,
                **_node_dict(node),
                **location,
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item["path"]),
            int(item["start_line"]),
        )
    )
    return ranked[:max_results]


def _feature_score(feature_query: str, node: Any, path: str) -> tuple[float, list[str]]:
    query = feature_query.casefold()
    tokens = _tokens(feature_query)
    haystack = " ".join(
        str(part)
        for part in (
            node.name,
            node.qualified_name,
            node.kind,
            node.granularity,
            path,
            Path(path).stem,
        )
        if part
    ).casefold()
    score = 0.0
    reasons: list[str] = []
    if query and query in haystack:
        score += 3.0
        reasons.append("phrase")
    if tokens:
        matched = [token for token in tokens if token in haystack]
        if matched:
            score += 2.0 * (len(matched) / len(tokens))
            reasons.append("tokens")
    if node.kind in {"function", "method", "class", "test"}:
        score += 0.2
    return score, reasons


def _knowledge_scores_by_path(
    analysis: WorkspaceAnalysis,
    feature_query: str,
) -> dict[str, float]:
    tokens = _tokens(feature_query)
    if not tokens:
        return {}
    scores: dict[str, float] = {}
    for item in analysis.knowledge.items:
        text = item.statement.casefold()
        matched = [token for token in tokens if token in text]
        if not matched:
            continue
        boost = min(1.5, len(matched) / len(tokens))
        for evidence in item.evidence_ids:
            scores[evidence] = max(scores.get(evidence, 0.0), boost)
    return scores


def _node_location(analysis: WorkspaceAnalysis, node: Any) -> dict[str, Any]:
    path = node.resource.path if node.resource is not None else ""
    file_path = (analysis.workspace.root / path).resolve()
    lines = _read_lines(file_path)
    line_count = len(lines)
    start_line = int(node.line or 1)
    if start_line < 1:
        start_line = 1
    if node.granularity != "symbol" or start_line > line_count:
        end_line = line_count
    else:
        end_line = _symbol_end_line(analysis, node, line_count)
    end_line = max(start_line, min(end_line, line_count or start_line))
    return {
        "start_line": start_line,
        "end_line": end_line,
        "insert_before_line": start_line,
        "insert_after_line": end_line,
        "preview": _preview(lines, start_line, end_line),
    }


def _symbol_end_line(
    analysis: WorkspaceAnalysis,
    node: Any,
    line_count: int,
) -> int:
    path = node.resource.path if node.resource is not None else ""
    file_path = analysis.workspace.root / path
    if file_path.suffix == ".py" and node.qualified_name:
        python_end = _python_symbol_end_line(file_path, node.qualified_name, node.line)
        if python_end is not None:
            return python_end
    next_lines = [
        int(other.line)
        for other in analysis.graph.nodes
        if other is not node
        and other.resource is not None
        and other.resource.path == path
        and other.granularity == "symbol"
        and int(other.line or 0) > int(node.line or 0)
    ]
    if next_lines:
        return min(next_lines) - 1
    return line_count


def _python_symbol_end_line(path: Path, qualified_name: str, line: int) -> int | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None
    for name, start, end in _python_symbol_ranges(tree):
        if name == qualified_name and start == line:
            return end
    return None


def _python_symbol_ranges(tree: ast.Module) -> list[tuple[str, int, int]]:
    ranges: list[tuple[str, int, int]] = []
    for item in tree.body:
        if isinstance(item, ast.ClassDef):
            ranges.append((item.name, item.lineno, int(item.end_lineno or item.lineno)))
            for member in item.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    ranges.append(
                        (
                            f"{item.name}.{member.name}",
                            member.lineno,
                            int(member.end_lineno or member.lineno),
                        )
                    )
        elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            ranges.append((item.name, item.lineno, int(item.end_lineno or item.lineno)))
    return ranges


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _preview(lines: list[str], start_line: int, end_line: int) -> str:
    if not lines:
        return ""
    start = max(1, start_line)
    end = min(len(lines), end_line)
    if end - start > 20:
        end = start + 20
    return "\n".join(
        f"{line_no}: {lines[line_no - 1]}"
        for line_no in range(start, end + 1)
    )


def _tokens(text: str) -> tuple[str, ...]:
    raw = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.casefold())
    tokens: list[str] = []
    for item in raw:
        tokens.append(item)
        tokens.extend(part for part in item.split("_") if part and part != item)
    return tuple(dict.fromkeys(tokens))


def _knowledge_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "statement": item.statement,
        "confidence": item.confidence,
        "evidence_ids": list(item.evidence_ids),
    }


__all__ = ["WorkspaceQueryTool"]

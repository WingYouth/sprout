"""Read-only project analysis tool backed by workspace intelligence."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from Sprout.task.models import Task
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec
from Sprout.workspace.graph import WorkspaceGraphBuilder
from Sprout.workspace.intelligence import WorkspaceIntelligence
from Sprout.workspace.knowledge import ProjectKnowledgeBuilder
from Sprout.workspace.models import Workspace
from Sprout.workspace.scanner import WorkspaceScanner


class ProjectAnalyzeTool:
    """Analyze a project workspace with safe built-in and optional system probes."""

    def __init__(self, *, intelligence: WorkspaceIntelligence | None = None) -> None:
        self._intelligence = intelligence
        self._scanner = WorkspaceScanner()
        self._graph_builder = WorkspaceGraphBuilder()
        self._knowledge_builder = ProjectKnowledgeBuilder()
        self.spec = ToolSpec(
            name="project_analyze",
            description=(
                "Read-only project analyzer for languages, manifests, README, Docker, "
                "compose, env keys, project database assets, interfaces, graph, and "
                "Sprout database topology."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace path to analyze.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Optional analysis focus.",
                    },
                    "include_system_tools": {
                        "type": "boolean",
                        "description": "Probe safe local analysis tools when present.",
                    },
                },
                "required": ["path"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        path_arg = arguments.get("path")
        if not isinstance(path_arg, str) or not path_arg:
            return ToolResult.failure("Argument 'path' must be a non-empty string")
        root = Path(path_arg).expanduser().resolve()
        if not root.is_dir():
            return ToolResult.failure(f"Workspace path does not exist: {root}")

        instruction = arguments.get("instruction")
        if not isinstance(instruction, str) or not instruction:
            instruction = "analyze project"

        workspace = Workspace(
            id=root.name or "workspace",
            root=root,
            kind=WorkspaceScanner.workspace_kind(root),
        )
        task = Task(
            id="project-analyze-tool",
            workspace_id=workspace.id,
            instruction=instruction,
            source="tool",
        )

        if self._intelligence is not None:
            analysis = await self._intelligence.analyze(workspace, task)
            manifest = analysis.manifest
            read_plan = analysis.read_plan
            graph = analysis.graph
            knowledge = analysis.knowledge
        else:
            manifest = self._scanner.scan(workspace)
            workspace = Workspace(
                id=workspace.id,
                root=workspace.root,
                kind=workspace.kind,
                revision=workspace.revision,
                manifest=manifest,
            )
            read_plan = self._scanner.build_read_plan(workspace, task)
            graph = self._graph_builder.build(workspace, read_plan)
            knowledge = self._knowledge_builder.build(workspace, manifest)
        payload: dict[str, Any] = {
            "workspace_id": workspace.id,
            "root": root.as_posix(),
            "languages": list(manifest.detected_languages),
            "framework_hints": list(manifest.framework_hints),
            "entry_points": list(manifest.entry_points),
            "test_commands": list(manifest.test_commands),
            "build_commands": list(manifest.build_commands),
            "read_plan_resources": len(read_plan.resources),
            "graph": {
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "node_kinds": sorted({node.kind for node in graph.nodes}),
                "relations": sorted({edge.relation for edge in graph.edges}),
            },
            "knowledge": [
                {
                    "kind": item.kind,
                    "statement": item.statement,
                    "confidence": item.confidence,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in knowledge.items
            ],
        }

        if arguments.get("include_system_tools") is True:
            payload["system_tools"] = await _system_tool_probe(root)

        return ToolResult.success(
            json.dumps(payload, ensure_ascii=False, indent=2),
            data=payload,
        )


async def _system_tool_probe(root: Path) -> dict[str, Any]:
    probes: dict[str, Any] = {
        "available": {},
        "outputs": {},
    }
    commands = {
        "git": ["git", "status", "--short"],
        "rg": ["rg", "--files", "--hidden", "-g", "!.git"],
        "tokei": ["tokei", "--output", "json"],
        "cloc": ["cloc", "--json", "."],
    }
    for name, command in commands.items():
        if shutil.which(command[0]) is None:
            probes["available"][name] = False
            continue
        probes["available"][name] = True
        result = await _run(command, root)
        probes["outputs"][name] = result
    if probes["available"].get("rg") and not (
        probes["available"].get("tokei") or probes["available"].get("cloc")
    ):
        probes["line_estimate"] = _estimate_lines_from_rg_output(
            root,
            probes["outputs"].get("rg", {}),
        )
    return probes


def _estimate_lines_from_rg_output(root: Path, rg_output: Mapping[str, Any]) -> dict[str, Any]:
    if rg_output.get("ok") is not True:
        return {
            "ok": False,
            "source": "rg --files fallback",
            "error": "rg file listing failed",
        }
    files = [
        line.strip()
        for line in str(rg_output.get("stdout") or "").splitlines()
        if line.strip()
    ]
    total_lines = 0
    counted_files = 0
    skipped_files = 0
    by_extension: dict[str, dict[str, int]] = {}
    for file_name in files:
        path = (root / file_name).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            skipped_files += 1
            continue
        if not path.is_file():
            skipped_files += 1
            continue
        try:
            data = path.read_bytes()
        except OSError:
            skipped_files += 1
            continue
        if b"\0" in data:
            skipped_files += 1
            continue
        lines = data.count(b"\n")
        if data and not data.endswith(b"\n"):
            lines += 1
        counted_files += 1
        total_lines += lines
        extension = relative.suffix.lower() or "<none>"
        bucket = by_extension.setdefault(extension, {"files": 0, "lines": 0})
        bucket["files"] += 1
        bucket["lines"] += lines
    return {
        "ok": True,
        "source": "rg --files fallback",
        "files": counted_files,
        "lines": total_lines,
        "skipped_files": skipped_files,
        "by_extension": dict(sorted(by_extension.items())),
    }


async def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=8)
    except TimeoutError:
        return {"ok": False, "error": "timeout"}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    output = stdout.decode("utf-8", errors="replace")
    error = stderr.decode("utf-8", errors="replace")
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "stdout": output[:8000],
        "stderr": error[:2000],
    }


__all__ = ["ProjectAnalyzeTool"]

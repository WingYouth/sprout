"""CLI/event-facing requirement strategy tool."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from Sprout.strategy.pipeline import StrategyPipeline
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec


class StrategyPlanTool:
    """Build an LLM-backed strategy report after intent routing."""

    def __init__(self, model, *, workspace_root: str | Path | None = None, knowledge=None) -> None:
        self._model = model
        self._root = Path(workspace_root or Path.cwd()).resolve()
        self._knowledge = knowledge
        self._pipeline = StrategyPipeline()
        self.spec = ToolSpec(
            name="strategy_plan",
            description=(
                "Analyze a natural-language requirement through project database "
                "search or project scan, then ask the configured LLM for a strategy report."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "path": {"type": "string"},
                    "analysis_mode": {
                        "type": "string",
                        "enum": ["scan", "database", "cross_validated"],
                        "default": "scan",
                    },
                },
                "required": ["requirement"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        requirement = arguments.get("requirement")
        if not isinstance(requirement, str) or not requirement.strip():
            return ToolResult.failure("Argument 'requirement' must be a non-empty string")
        root = Path(str(arguments.get("path") or self._root)).expanduser().resolve()
        if not root.is_dir():
            return ToolResult.failure(f"Project path does not exist: {root}")
        mode = str(arguments.get("analysis_mode") or "scan")
        try:
            if mode == "database":
                if self._knowledge is None:
                    return ToolResult.failure("Project database search is not configured")
                plan = await self._pipeline.plan_from_project_database(
                    root, requirement, self._knowledge.search, self._model
                )
            elif mode == "cross_validated":
                if self._knowledge is None:
                    return ToolResult.failure("Project database search is not configured")
                plan = await self._pipeline.plan_cross_validated(
                    root, requirement, self._knowledge.search, self._model
                )
            else:
                plan = await self._pipeline.plan_user_request_with_model(
                    root, requirement, self._model
                )
        except Exception as exc:  # Tool boundary returns a readable CLI error.
            return ToolResult.failure(f"Strategy planning failed: {exc}")
        return ToolResult.success(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, default=str),
            data=plan.to_dict(),
        )

"""Orchestrator backend protocol."""

from __future__ import annotations

from typing import Protocol

from Sprout.orchestration.models import ExecutionGraph
from Sprout.task.models import TaskResult


class OrchestratorBackend(Protocol):
    async def execute(
        self,
        graph: ExecutionGraph,
        *,
        handler=None,
        recorder=None,
        budget=None,
    ) -> TaskResult:
        ...

"""Local sequential orchestrator backend."""

from __future__ import annotations

from Sprout.orchestration.models import ExecutionGraph
from Sprout.orchestration.service import SequentialOrchestrator
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.task.models import TaskResult


class LocalOrchestratorBackend:
    """Runs execution graphs in-process using the sequential orchestrator."""

    def __init__(self, metadata: MetadataStore) -> None:
        self._metadata = metadata

    async def execute(
        self,
        graph: ExecutionGraph,
        *,
        handler=None,
        recorder=None,
        budget=None,
    ) -> TaskResult:
        return await SequentialOrchestrator(self._metadata).execute(
            graph,
            handler=handler,
            recorder=recorder,
            budget=budget,
        )

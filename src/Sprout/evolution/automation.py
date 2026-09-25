"""Scheduler-friendly growth automation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.evolution.candidate_manager import CandidateManager
from Sprout.evolution.consolidation import ArtifactConsolidator
from Sprout.evolution.maintenance import ArtifactMaintenance
from Sprout.evolution.trajectory_growth import TrajectoryGrowthService
from Sprout.storage.contracts.metadata import MetadataStore

if TYPE_CHECKING:
    from Sprout.scheduler.scheduler import Scheduler


class GrowthAutomation:
    """Runs trajectory collection and candidate evaluation as one maintenance step."""

    def __init__(
        self,
        metadata: MetadataStore,
        workspace_id: str,
        trajectory_dir: str | Path,
        *,
        manager: CandidateManager | None = None,
        consolidator: ArtifactConsolidator | None = None,
        maintenance: ArtifactMaintenance | None = None,
        runtime: object | None = None,
    ) -> None:
        self._metadata = metadata
        self._workspace_id = workspace_id
        self._trajectory_dir = Path(trajectory_dir)
        self._manager = manager or CandidateManager(
            metadata,
            # Publishing a SKILL is how learned knowledge reaches the agent:
            # ``_publish`` registers it on this registry, and the agent reads
            # skills from there. Without it the manager publishes into a void —
            # the artifact is marked PUBLISHED and nothing changes for the next
            # task.
            skills=getattr(runtime, "skills", None),
            knowledge=getattr(runtime.storage, "knowledge", None)
            if runtime is not None
            else None,
            events=getattr(runtime, "events", None),
        )
        self._consolidator = consolidator or ArtifactConsolidator()
        self._maintenance = maintenance or ArtifactMaintenance()

    async def run_once(self) -> dict:
        service = TrajectoryGrowthService(self._metadata)
        candidates = await service.collect(self._workspace_id, self._trajectory_dir)
        changes = await self._manager.evaluate_all()
        consolidated = await self._consolidator.consolidate(self._metadata)
        maintained = await self._maintenance.maintain(self._metadata)
        return {
            "candidates_collected": len(candidates),
            "status_changes": changes,
            "consolidated": consolidated,
            "maintained": maintained,
        }

    def attach(self, scheduler: Scheduler, *, interval_seconds: float = 300.0) -> None:
        async def job() -> None:
            await self.run_once()

        scheduler.every("growth-automation", interval_seconds, job)

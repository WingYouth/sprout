"""Unified growth facade: the single entry point of the growth pipeline.

Everything routes through trajectory collection and the candidate manager
(SEMA spec 16.3); there is no second, observation-based track anymore.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.events import EventBus
from Sprout.evolution.candidate_manager import CandidateManager
from Sprout.evolution.trajectory_growth import TrajectoryGrowthService
from Sprout.skills.registry import SkillRegistry
from Sprout.skills.repository import SkillRepository
from Sprout.storage.contracts.knowledge import KnowledgeStore
from Sprout.storage.contracts.metadata import MetadataStore


class UnifiedGrowthService:
    """Single facade for the trajectory-driven growth pipeline."""

    def __init__(
        self,
        metadata: MetadataStore,
        observations: object | None = None,
        *,
        skills: SkillRegistry | None = None,
        skill_repository: SkillRepository | None = None,
        knowledge: KnowledgeStore | None = None,
        events: EventBus | None = None,
        manager: CandidateManager | None = None,
    ) -> None:
        # ``observations`` is accepted for call-site compatibility but unused:
        # candidates are extracted from trajectories, not live observations.
        self._metadata = metadata
        self._events = events
        if manager is None:
            # Publishing must behave the same from every entry point: a skill
            # lands in the live registry and repository, project knowledge in
            # the knowledge store, regardless of which caller wires the layer.
            manager = CandidateManager(
                metadata,
                skills=skills,
                skill_repository=skill_repository,
                knowledge=knowledge,
                events=events,
            )
        self._manager = manager

    async def collect_trajectories(
        self,
        workspace_id: str,
        trajectory_dir: str | Path,
    ) -> list:
        return await TrajectoryGrowthService(
            self._metadata,
            events=self._events,
        ).collect(
            workspace_id,
            trajectory_dir,
        )

    async def evaluate_all(self) -> dict[str, str]:
        return await self._manager.evaluate_all()

    async def approve(self, artifact_id: str, *, decided_by: str = "cli"):
        return await self._manager.approve(artifact_id, decided_by=decided_by)

    async def reject(self, artifact_id: str, *, reason: str = ""):
        return await self._manager.reject(artifact_id, reason=reason)

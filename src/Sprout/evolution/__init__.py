"""Growth layer: async, auditable, and never imported by Runtime.

Single pipeline (SEMA spec 16.3):
    Trajectory -> Eligibility -> Signals -> GrowthRouter -> Candidate
    -> Replay -> Hard Gates -> Utility -> CandidateManager -> Publish

Dependency direction (enforced by convention):
    evolution -> Runtime public API / storage contracts
    Runtime   ✗ evolution
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from Sprout.evolution.automation import GrowthAutomation
from Sprout.evolution.candidate import GrowthCandidateBuilder
from Sprout.evolution.candidate_evaluator import (
    CandidateEvaluation,
    CandidateEvaluator,
)
from Sprout.evolution.candidate_manager import CandidateManager
from Sprout.evolution.consolidation import ArtifactConsolidator
from Sprout.evolution.eligibility import EligibilityDecision, LearningEligibilityFilter
from Sprout.evolution.growth_router import GrowthRouter, RoutingDecision
from Sprout.evolution.hard_gate import (
    GateChecks,
    HardGateEvaluator,
    HardGateResult,
)
from Sprout.evolution.maintenance import ArtifactMaintenance
from Sprout.evolution.models import (
    EvidenceRef,
    GrowthSignal,
    SignalType,
)
from Sprout.evolution.replay import ReplayCaseBuilder, ReplayEvaluator, ReplayReport
from Sprout.evolution.replay_runner import ReplayResult, ReplayRunner
from Sprout.evolution.trajectory_growth import (
    StablePathExtractor,
    TrajectoryGrowthService,
    TrajectorySignalExtractor,
)
from Sprout.evolution.unified import UnifiedGrowthService
from Sprout.evolution.utility import UtilityEvaluator, UtilityReport

logger = logging.getLogger("sprout.evolution")

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime

__all__ = [
    "ArtifactConsolidator",
    "ArtifactMaintenance",
    "CandidateEvaluation",
    "CandidateEvaluator",
    "CandidateManager",
    "EligibilityDecision",
    "EvidenceRef",
    "GateChecks",
    "GrowthAutomation",
    "GrowthCandidateBuilder",
    "GrowthRouter",
    "GrowthSignal",
    "HardGateEvaluator",
    "HardGateResult",
    "LearningEligibilityFilter",
    "ReplayCaseBuilder",
    "ReplayEvaluator",
    "ReplayReport",
    "ReplayResult",
    "ReplayRunner",
    "RoutingDecision",
    "SignalType",
    "TrajectoryGrowthService",
    "StablePathExtractor",
    "TrajectorySignalExtractor",
    "UnifiedGrowthService",
    "UtilityEvaluator",
    "UtilityReport",
    "attach_evolution",
    "build_candidate_manager",
]


def build_candidate_manager(runtime: Runtime, settings: Settings) -> CandidateManager:
    """The single wiring point for candidate publishing.

    Every entry point (CLI, attached services) builds its manager here, so a
    published skill always lands in the live registry and on disk, and
    published project knowledge always reaches the knowledge store.
    """
    from Sprout.skills.repository import SkillRepository

    if runtime.storage.metadata is None:
        raise RuntimeError("MetadataStore is not configured")
    return CandidateManager(
        runtime.storage.metadata,
        skills=runtime.skills,
        skill_repository=SkillRepository(settings.skills_dir),
        knowledge=runtime.storage.knowledge,
        events=runtime.events,
    )


def attach_evolution(runtime: Runtime, settings: Settings) -> UnifiedGrowthService | None:
    """Wire the growth layer onto a runtime; called by entry points, never by Runtime.

    The growth layer is trajectory-driven: candidates are collected from
    recorded task trajectories, never from live event observation. Publishing
    is wired through :func:`build_candidate_manager` so this path behaves
    exactly like the CLI path.
    """
    if not settings.evolution.enabled:
        return None
    if runtime.storage.metadata is None:
        return None
    service = UnifiedGrowthService(
        runtime.storage.metadata,
        runtime.storage.observations,
        manager=build_candidate_manager(runtime, settings),
        events=runtime.events,
    )
    _listen_for_evolution_intent(runtime, settings, service)
    return service


def _listen_for_evolution_intent(
    runtime: Runtime,
    settings: Settings,
    service: UnifiedGrowthService,
) -> None:
    """Run one growth sweep when the user asks for one.

    The router recognises an evolution intent and publishes
    ``INTENT_EVOLUTION_REQUESTED``, but nothing consumed it: the request was
    routed, recorded, and then dropped. Attaching the growth layer is the
    sanctioned seam for this (``runtime/`` must not import ``evolution/``), so
    the subscription lives here.

    The sweep is fire-and-forget because the intent is handled on the online
    turn path -- the user gets an acknowledgement immediately while collection
    proceeds in the background. It stops at VALIDATED: publishing a skill
    changes what every later turn is told, so it stays a human ``approve``.
    """
    from Sprout.events import INTENT_EVOLUTION_REQUESTED

    async def on_intent(event) -> None:
        workspace_id = str(dict(event.payload or {}).get("workspace_id") or "")
        if not workspace_id:
            # Trajectories are read per workspace; without one there is
            # nothing to sweep and no trajectory directory to look in.
            return
        try:
            await service.collect_trajectories(
                workspace_id, settings.storage.trajectory_dir
            )
            await service.evaluate_all()
        except Exception:  # noqa: BLE001 - growth must never break a user turn
            logger.warning("Growth sweep for %s failed", workspace_id, exc_info=True)

    def schedule(event) -> None:
        runtime.schedule_background(on_intent(event))

    runtime.events.subscribe(INTENT_EVOLUTION_REQUESTED, schedule)

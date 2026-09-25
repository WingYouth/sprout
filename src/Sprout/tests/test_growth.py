"""Growth layer tests: signals, the single pipeline, and artifact lifecycle.

The growth layer has exactly one track (Herness spec 16.3): trajectories are
collected, filtered, turned into signals, replayed, gated, and finally published
through the candidate manager. There is no observation-based second track.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from Sprout.artifacts.models import Artifact, ArtifactKind, ArtifactStatus
from Sprout.evolution import (
    CandidateManager,
    EvidenceRef,
    GrowthCandidateBuilder,
    GrowthRouter,
    GrowthSignal,
    LearningEligibilityFilter,
    StablePathExtractor,
    TrajectoryGrowthService,
    TrajectorySignalExtractor,
    UnifiedGrowthService,
)
from Sprout.skills.registry import SkillRegistry
from Sprout.skills.repository import SkillRepository
from Sprout.storage.local.sqlite.metadata import open_metadata_store
from Sprout.trajectory.models import Trajectory, TrajectoryEvent, TrajectoryStatus
from Sprout.trajectory.recorder import JsonlTrajectoryRecorder

# -- GrowthSignal validation ---------------------------------------------------


def test_growth_signal_requires_evidence() -> None:
    with pytest.raises(ValueError, match="must reference evidence"):
        GrowthSignal(
            "repeated_failure", "Missing retry", "Repeated failure", (), 0.8, 0.5, 0.7, 0.4
        )


def test_growth_signal_accepts_traceable_evidence() -> None:
    signal = GrowthSignal(
        "repeated_failure",
        "Missing retry",
        "Repeated failure",
        (EvidenceRef("event", "evt-1"),),
        0.8,
        0.5,
        0.7,
        0.4,
    )
    assert signal.evidence[0].source_id == "evt-1"


def test_growth_signal_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValueError, match="confidence"):
        GrowthSignal(
            "repeated_failure",
            "Odd scores",
            "d",
            (EvidenceRef("event", "e1"),),
            1.5,
            0.5,
            0.5,
            0.5,
        )
    with pytest.raises(ValueError, match="impact_score"):
        GrowthSignal(
            "repeated_failure",
            "Odd scores",
            "d",
            (EvidenceRef("event", "e1"),),
            0.5,
            -0.1,
            0.5,
            0.5,
        )


# -- helpers -------------------------------------------------------------------


def _signal(
    signal_type: str = "repeated_failure",
    title: str = "Repeated ValueError failures",
) -> GrowthSignal:
    return GrowthSignal(
        type=signal_type,
        title=title,
        description="Two failures observed while running the test suite.",
        evidence=(EvidenceRef("trajectory_event", "evt-1"),),
        confidence=0.8,
        impact_score=0.5,
        recurrence_score=0.7,
        severity_score=0.4,
    )


def _artifact(
    *,
    name: str = "repeated-valueerror-failures",
    content: str | None = None,
    kind: ArtifactKind = ArtifactKind.SKILL,
    status: ArtifactStatus = ArtifactStatus.CANDIDATE,
) -> Artifact:
    body = content or (
        "When a command fails, inspect the error output before retrying, and "
        "record the failing command so the next attempt starts from evidence."
    )
    return Artifact(
        kind=kind,
        name=name,
        version="0.1.0",
        content=body,
        status=status,
        scope="workspace",
        evidence_ids=("evt-1", "evt-2", "evt-3"),
        metadata={"diagnosis": "Two failures observed.", "rationale": "Repeated failures"},
    )


def _trajectory(*names: str, status: TrajectoryStatus = TrajectoryStatus.COMPLETED) -> Trajectory:
    return Trajectory(
        task_id="task-1",
        workspace_id="ws-1",
        status=status,
        events=tuple(
            TrajectoryEvent(name=name, task_id="task-1") for name in names
        ),
    )


# -- routing and candidate building -------------------------------------------


def test_router_maps_repeated_failure_to_skill() -> None:
    decision = GrowthRouter().route(_signal())
    assert decision.artifact_kind is ArtifactKind.SKILL
    assert decision.scope == "workspace"


def test_router_maps_knowledge_gap_to_project_knowledge() -> None:
    decision = GrowthRouter().route(_signal("knowledge_gap", "Missing setup steps"))
    assert decision.artifact_kind is ArtifactKind.PROJECT_KNOWLEDGE


def test_candidate_builder_slugs_the_title_and_starts_as_candidate() -> None:
    candidate = GrowthCandidateBuilder().build(_signal())

    assert candidate.artifact is not None
    assert candidate.artifact.status is ArtifactStatus.CANDIDATE
    assert candidate.artifact.name == "repeated-valueerror-failures"
    assert candidate.evidence_ids == ("evt-1",)
    assert candidate.diagnosis == "Two failures observed while running the test suite."


# -- eligibility ---------------------------------------------------------------


def test_eligibility_accepts_a_completed_trajectory() -> None:
    decision = LearningEligibilityFilter().evaluate(_trajectory("node.completed"))
    assert decision.eligible


def test_eligibility_requires_meaningful_events() -> None:
    decision = LearningEligibilityFilter().evaluate(_trajectory("telemetry.beat"))
    assert not decision.eligible
    assert "meaningful" in decision.reason


def test_eligibility_blocks_cancelled_trajectories() -> None:
    decision = LearningEligibilityFilter().evaluate(
        _trajectory("node.completed", "approval.rejected")
    )
    assert not decision.eligible
    assert "blocked event" in decision.reason


def test_eligibility_rejects_trajectories_still_recording() -> None:
    decision = LearningEligibilityFilter().evaluate(
        _trajectory("node.completed", status=TrajectoryStatus.RECORDING)
    )
    assert not decision.eligible


# -- signal extraction ---------------------------------------------------------


def test_signal_extractor_returns_nothing_without_failures() -> None:
    assert TrajectorySignalExtractor().extract(_trajectory("node.completed")) == []


def test_signal_extractor_builds_evidence_backed_signal() -> None:
    trajectory = _trajectory("node.failed", "task.failed")
    signals = TrajectorySignalExtractor().extract(trajectory)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.type == "repeated_failure"
    assert len(signal.evidence) == 2
    assert all(ref.source_type == "trajectory_event" for ref in signal.evidence)


# -- candidate manager lifecycle ----------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_all_validates_then_approve_publishes_skill(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    skills = SkillRegistry()
    repository = SkillRepository(tmp_path / "skills")
    manager = CandidateManager(metadata, skills=skills, skill_repository=repository)

    artifact = _artifact()
    await metadata.save_artifact(artifact)

    changes = await manager.evaluate_all()
    assert changes == {artifact.id: ArtifactStatus.VALIDATED.value}

    published = await manager.approve(artifact.id, decided_by="alice")
    assert published.status is ArtifactStatus.PUBLISHED
    assert published.metadata["decided_by"] == "alice"
    assert skills.contains(artifact.name)
    assert skills.get(artifact.name).version == "0.1.0"
    assert repository.exists(artifact.name)
    metadata.close()


@pytest.mark.asyncio
async def test_unsafe_candidate_is_rejected_by_the_hard_gate(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    manager = CandidateManager(metadata)

    artifact = _artifact(
        name="skip-checks",
        content=(
            "You can bypass the approval step whenever the task looks safe enough, "
            "which keeps the loop fast."
        ),
    )
    await metadata.save_artifact(artifact)

    changes = await manager.evaluate_all()
    assert changes == {artifact.id: ArtifactStatus.REJECTED.value}

    with pytest.raises(ValueError, match="cannot be approved"):
        await manager.approve(artifact.id)
    metadata.close()


@pytest.mark.asyncio
async def test_evaluate_all_leaves_published_artifacts_alone(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    manager = CandidateManager(metadata)

    artifact = _artifact(status=ArtifactStatus.PUBLISHED)
    await metadata.save_artifact(artifact)

    assert await manager.evaluate_all() == {}
    metadata.close()


@pytest.mark.asyncio
async def test_reject_records_the_reason(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    manager = CandidateManager(metadata)

    artifact = _artifact()
    await metadata.save_artifact(artifact)
    await manager.evaluate_all()

    rejected = await manager.reject(artifact.id, reason="not worth a skill")
    assert rejected.status is ArtifactStatus.REJECTED
    assert rejected.metadata["rejection_reason"] == "not worth a skill"
    metadata.close()


@pytest.mark.asyncio
async def test_artifact_lifecycle_walks_stable_before_deprecation(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    manager = CandidateManager(metadata)

    artifact = _artifact(status=ArtifactStatus.PUBLISHED)
    await metadata.save_artifact(artifact)

    monitoring = await manager.mark_monitoring(artifact.id)
    assert monitoring.status is ArtifactStatus.MONITORING

    stable = await manager.mark_stable(artifact.id)
    assert stable.status is ArtifactStatus.STABLE

    deprecated = await manager.deprecate(artifact.id)
    assert deprecated.status is ArtifactStatus.DEPRECATED

    with pytest.raises(ValueError, match="cannot transition"):
        await manager.mark_monitoring(artifact.id)
    metadata.close()


# -- trajectory collection end to end -----------------------------------------


@pytest.mark.asyncio
async def test_unified_service_collects_and_persists_candidates(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    trajectory_dir = tmp_path / "trajectories"
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    service = UnifiedGrowthService(metadata)
    candidates = await service.collect_trajectories("ws-1", trajectory_dir)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.artifact is not None
    assert candidate.artifact.kind is ArtifactKind.SKILL
    assert candidate.artifact.status is ArtifactStatus.CANDIDATE

    stored = await metadata.list_artifacts()
    assert [item.id for item in stored] == [candidate.artifact.id]

    # The collected candidate then flows through the same approval path.
    changes = await service.evaluate_all()
    assert changes[candidate.artifact.id] == ArtifactStatus.VALIDATED.value
    metadata.close()


@pytest.mark.asyncio
async def test_unified_service_skips_ineligible_trajectories(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    trajectory_dir = tmp_path / "trajectories"
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "approval.rejected"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    candidates = await UnifiedGrowthService(metadata).collect_trajectories(
        "ws-1", trajectory_dir
    )

    assert candidates == []
    assert await metadata.list_artifacts() == []
    metadata.close()


@pytest.mark.asyncio
async def test_collect_returns_empty_for_a_missing_directory(tmp_path) -> None:
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    service = TrajectoryGrowthService(metadata)

    assert await service.collect("ws-1", tmp_path / "absent") == []
    metadata.close()


# -- entry point wiring ---------------------------------------------------------


def _wired_runtime(tmp_path):
    """A runtime with a metadata store, for attach/build wiring tests."""
    from Sprout.config.settings import Settings
    from Sprout.tests.conftest import build_runtime

    runtime, _ = build_runtime()
    runtime.storage.metadata = open_metadata_store(str(tmp_path / "herness.db"))
    settings = Settings()
    settings.evolution.enabled = True
    settings.skills_dir = str(tmp_path / "skills")
    return runtime, settings


@pytest.mark.asyncio
async def test_attach_evolution_publishes_into_the_live_registry(tmp_path) -> None:
    """The attached service must publish like the CLI path (same wiring)."""
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None

    service = attach_evolution(runtime, settings)
    assert service is not None

    artifact = _artifact(status=ArtifactStatus.VALIDATED)
    await metadata.save_artifact(artifact)

    published = await service.approve(artifact.id, decided_by="tester")
    assert published.status is ArtifactStatus.PUBLISHED
    assert runtime.skills.contains(artifact.name)
    assert SkillRepository(settings.skills_dir).exists(artifact.name)
    metadata.close()


@pytest.mark.asyncio
async def test_attach_evolution_publishes_knowledge_artifacts(tmp_path) -> None:
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None

    service = attach_evolution(runtime, settings)
    assert service is not None

    artifact = _artifact(
        name="retry-backoff",
        kind=ArtifactKind.PROJECT_KNOWLEDGE,
        status=ArtifactStatus.VALIDATED,
    )
    await metadata.save_artifact(artifact)

    published = await service.approve(artifact.id, decided_by="tester")
    assert published.status is ArtifactStatus.PUBLISHED
    stored = await runtime.storage.knowledge.get(f"ka-{artifact.id}")
    assert stored is not None
    assert stored.content == artifact.content
    assert stored.evidence_ids == artifact.evidence_ids
    metadata.close()


def test_attach_evolution_returns_none_without_metadata(tmp_path) -> None:
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    runtime.storage.metadata = None
    assert attach_evolution(runtime, settings) is None


def test_attach_evolution_returns_none_when_disabled(tmp_path) -> None:
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    settings.evolution.enabled = False
    assert attach_evolution(runtime, settings) is None


@pytest.mark.asyncio
async def test_publishing_emits_growth_events(tmp_path) -> None:
    """Every publish announces itself: skill.published and evolution.published."""
    from Sprout.events import EVOLUTION_PUBLISHED, SKILL_PUBLISHED
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None
    seen: list[str] = []
    runtime.events.subscribe("*", lambda event: seen.append(event.name))

    service = attach_evolution(runtime, settings)
    assert service is not None
    artifact = _artifact(status=ArtifactStatus.VALIDATED)
    await metadata.save_artifact(artifact)

    await service.approve(artifact.id, decided_by="tester")
    assert SKILL_PUBLISHED in seen
    assert EVOLUTION_PUBLISHED in seen
    metadata.close()


@pytest.mark.asyncio
async def test_collecting_emits_signal_and_proposal_events(tmp_path) -> None:
    """A surviving candidate announces its signal and its proposal."""
    from Sprout.events import EVOLUTION_PROPOSAL, EVOLUTION_SIGNAL
    from Sprout.evolution import UnifiedGrowthService

    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    trajectory_dir = tmp_path / "trajectories"
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    seen: list[str] = []
    service = UnifiedGrowthService(metadata, events=_RecordingBus(seen))
    await service.collect_trajectories("ws-1", trajectory_dir)

    assert EVOLUTION_SIGNAL in seen
    assert EVOLUTION_PROPOSAL in seen
    metadata.close()


class _RecordingBus:
    """Minimal EventBus stand-in that records published event names."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def publish(self, event) -> None:
        self._names.append(event.name)


# -- learning from successful runs --------------------------------------------


def _run(*node_types: str, task_id: str = "t") -> Trajectory:
    """A completed trajectory whose node path is the given types."""
    return Trajectory(
        task_id=task_id,
        workspace_id="ws-1",
        status=TrajectoryStatus.COMPLETED,
        events=tuple(
            TrajectoryEvent(
                name="node.started",
                task_id=task_id,
                payload={"node_id": f"{task_id}:{kind}", "type": kind},
            )
            for kind in node_types
        ),
    )


def test_stable_path_needs_repetition() -> None:
    """One run is not a pattern; two can be coincidence.

    The failure-only extractor could not express this at all — it reads one
    trajectory — which is why stability had to be decided across a batch.
    """
    path = ("read", "sandbox", "plan", "agent", "evaluation", "approval", "apply")

    assert StablePathExtractor().extract([_run(*path, task_id="a")]) == []
    assert StablePathExtractor().extract(
        [_run(*path, task_id="a"), _run(*path, task_id="b")]
    ) == []
    assert len(
        StablePathExtractor().extract(
            [_run(*path, task_id=n) for n in ("a", "b", "c")]
        )
    ) == 1


def test_stable_path_ignores_failed_runs() -> None:
    """A path is learned from runs that worked, not from ones that broke."""
    path = ("read", "sandbox", "plan", "agent", "apply")
    healthy = [_run(*path, task_id=n) for n in ("a", "b", "c")]
    broken = [
        _trajectory("node.started", "task.failed", status=TrajectoryStatus.FAILED)
        for _ in range(5)
    ]

    assert len(StablePathExtractor().extract(healthy + broken)) == 1


def test_stable_path_separates_different_shapes() -> None:
    """Different node paths are different patterns, not one merged signal."""
    short = ("read", "agent", "apply")
    long = ("read", "sandbox", "plan", "agent", "evaluation", "approval", "apply")
    runs = [_run(*short, task_id=f"s{n}") for n in range(3)] + [
        _run(*long, task_id=f"l{n}") for n in range(3)
    ]

    signals = StablePathExtractor().extract(runs)

    assert len(signals) == 2
    assert len({signal.title for signal in signals}) == 2


def test_stable_path_deduplicates_revisits() -> None:
    """A resumed run revisits nodes; the shape must not double-count them.

    A live trajectory showed ``evaluation`` and ``approval`` twice each
    because granting a decision resumes the graph.
    """
    retried = _run(
        "read", "agent", "evaluation", "evaluation", "approval", "approval", "apply"
    )

    assert StablePathExtractor._node_path(retried) == (
        "read",
        "agent",
        "evaluation",
        "approval",
        "apply",
    )


def test_stable_path_signal_routes_to_a_workflow_artifact() -> None:
    """The signal must land on a kind `growth_router` already understands."""
    path = ("read", "sandbox", "plan", "agent", "evaluation", "approval", "apply")
    signal = StablePathExtractor().extract(
        [_run(*path, task_id=n) for n in ("a", "b", "c")]
    )[0]

    assert signal.type == "behavior_pattern"
    assert GrowthRouter().route(signal).artifact_kind is ArtifactKind.WORKFLOW


def test_batch_signal_evidence_is_grounded_in_one_run() -> None:
    """Replay requires every evidence reference to come from the trajectory
    under evaluation. A signal drawn from a batch mixes runs, so it scores
    zero on that check unless it is narrowed first — which cost the candidate
    the 0.4 it needed to clear the gate."""
    path = ("read", "agent", "apply")
    runs = [_run(*path, task_id=n) for n in ("a", "b", "c")]
    signal = StablePathExtractor().extract(runs)[0]

    grounded = TrajectoryGrowthService._ground(signal, runs[0])

    own_events = {event.id for event in runs[0].events}
    assert all(ref.source_id in own_events for ref in grounded.evidence)
    assert grounded.evidence, "a signal without evidence is rejected outright"


@pytest.mark.asyncio
async def test_approve_publishes_a_workflow_too(tmp_path) -> None:
    """A learned workflow must reach the agent, like a skill does.

    Regression: ``_publish`` handled only SKILL and PROJECT_KNOWLEDGE, so a
    WORKFLOW artifact — which is what ``behavior_pattern`` routes to — was
    marked PUBLISHED and nothing else happened. Nothing consumed it, so a
    learned pattern could never influence the next task.
    """
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    skills = SkillRegistry()
    manager = CandidateManager(metadata, skills=skills)

    artifact = _artifact(
        name="stable-path",
        kind=ArtifactKind.WORKFLOW,
        content="Tasks here run read -> plan -> agent -> evaluation -> apply.",
    )
    await metadata.save_artifact(artifact)
    await manager.evaluate_all()

    published = await manager.approve(artifact.id, decided_by="alice")

    assert published.status is ArtifactStatus.PUBLISHED
    assert skills.contains("stable-path"), (
        "a published workflow must be readable by the agent"
    )
    skill = skills.get("stable-path")
    assert "read -> plan -> agent" in skill.instructions


@pytest.mark.asyncio
async def test_published_skill_is_actually_injectable(tmp_path) -> None:
    """An approved skill must survive the trust gate, not just be registered.

    Regression: ``_publish`` built ``Skill(...)`` without ``trust``, so it took
    the ``untrusted`` default. ``skills.contains`` only checks the enabled flag,
    so the older test passed while ``AgentContext.visible_skills`` — which
    requires ``trust == "trusted"`` — returned nothing. The learned knowledge
    never reached the prompt in the default ``progressive`` disclosure mode.
    """
    from Sprout.context.context import AgentContext
    from Sprout.session.models import Session

    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    skills = SkillRegistry()
    manager = CandidateManager(metadata, skills=skills)

    artifact = _artifact(name="stable-path")
    await metadata.save_artifact(artifact)
    await manager.evaluate_all()
    await manager.approve(artifact.id, decided_by="alice")

    skill = skills.get("stable-path")
    assert skill.trust == "trusted", f"approved skill is {skill.trust!r}"

    context = AgentContext(
        session=Session(id="s1", user_id="u1"),
        skills={"stable-path": skill},
    )
    assert context.skill_disclosure == "progressive"
    assert [s.name for s in context.visible_skills()] == ["stable-path"]
    metadata.close()


@pytest.mark.asyncio
async def test_publishing_without_a_registry_is_not_an_error(tmp_path) -> None:
    """The registry is optional; publishing must still record the artifact."""
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    manager = CandidateManager(metadata)
    artifact = _artifact(kind=ArtifactKind.WORKFLOW)
    await metadata.save_artifact(artifact)
    await manager.evaluate_all()

    published = await manager.approve(artifact.id, decided_by="alice")

    assert published.status is ArtifactStatus.PUBLISHED


@pytest.mark.asyncio
async def test_growth_automation_wires_the_runtime_registry(tmp_path) -> None:
    """Learned knowledge reaches the agent only if the manager has the registry.

    Regression: ``GrowthAutomation`` built ``CandidateManager(metadata)`` with
    no registry, so ``_publish`` skipped registration and publishing changed
    nothing for the next task — the artifact was PUBLISHED into a void.
    """
    from Sprout.evolution.automation import GrowthAutomation

    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    skills = SkillRegistry()
    runtime = SimpleNamespace(
        skills=skills,
        events=None,
        storage=SimpleNamespace(knowledge=None),
    )

    automation = GrowthAutomation(
        metadata, "ws-1", tmp_path, runtime=runtime
    )

    assert automation._manager._skills is skills


# -- consolidation must not eat a published artifact --------------------------


@pytest.mark.asyncio
async def test_consolidate_never_deprecates_a_published_artifact(tmp_path) -> None:
    """A second collection pass must not silently deprecate the live skill.

    ``CandidateManager.approve`` is a human decision (it records ``decided_by``),
    so a PUBLISHED artifact outranks an unreviewed duplicate no matter how
    recent the duplicate is. Regression: ``consolidate`` sorted by ``updated_at``
    and skipped only DEPRECATED/REJECTED/ROLLED_BACK, so a freshly-minted
    same-name candidate deprecated the PUBLISHED skill it duplicated.
    """
    from Sprout.evolution.consolidation import ArtifactConsolidator

    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    published = _artifact(status=ArtifactStatus.PUBLISHED)
    await metadata.save_artifact(published)

    # Same name, later updated_at: exactly the shape a re-collection minted.
    duplicate = replace(
        _artifact(name=published.name, status=ArtifactStatus.VALIDATED),
        updated_at=published.updated_at + timedelta(seconds=5),
    )
    await metadata.save_artifact(duplicate)

    changes = await ArtifactConsolidator().consolidate(metadata)

    assert published.id not in changes, "consolidate deprecated the published skill"
    surviving = {a.id: a.status for a in await metadata.list_artifacts()}
    assert surviving[published.id] is ArtifactStatus.PUBLISHED
    metadata.close()


@pytest.mark.asyncio
async def test_consolidate_still_deprecates_unreviewed_duplicates(tmp_path) -> None:
    """The published exemption must not disable consolidation entirely."""
    from Sprout.evolution.consolidation import ArtifactConsolidator

    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    older = _artifact(status=ArtifactStatus.CANDIDATE)
    await metadata.save_artifact(older)
    newer = replace(
        _artifact(name=older.name, status=ArtifactStatus.CANDIDATE),
        updated_at=older.updated_at + timedelta(seconds=5),
    )
    await metadata.save_artifact(newer)

    changes = await ArtifactConsolidator().consolidate(metadata)

    assert changes == {older.id: ArtifactStatus.DEPRECATED.value}
    metadata.close()


# -- collection is idempotent -------------------------------------------------


@pytest.mark.asyncio
async def test_recollecting_the_same_trajectory_does_not_mint_a_duplicate(tmp_path) -> None:
    """Running collection twice over the same trajectory must not duplicate.

    Trajectory files are re-globbed on every pass, so the same signal yields a
    fresh ``uuid4``-keyed artifact each time. The dedup key is the artifact
    ``name``; this asserts it is actually honoured.
    """
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    trajectory_dir = tmp_path / "trajectories"
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    service = UnifiedGrowthService(metadata)
    first = await service.collect_trajectories("ws-1", trajectory_dir)
    assert len(first) == 1

    second = await service.collect_trajectories("ws-1", trajectory_dir)

    stored = await metadata.list_artifacts()
    assert [a.id for a in stored] == [first[0].artifact.id], (
        "a second pass minted a duplicate artifact for the same name"
    )
    # The re-collection reuses the existing row rather than proposing a new one.
    assert [c.artifact.id for c in second] == [first[0].artifact.id]
    metadata.close()


@pytest.mark.asyncio
async def test_recollection_does_not_resurrect_a_rejected_candidate(tmp_path) -> None:
    """A human rejection is a decision; re-collection must not undo it."""
    metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    trajectory_dir = tmp_path / "trajectories"
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    service = UnifiedGrowthService(metadata)
    first = await service.collect_trajectories("ws-1", trajectory_dir)
    artifact_id = first[0].artifact.id
    rejected = replace(
        first[0].artifact, status=ArtifactStatus.REJECTED
    )
    await metadata.save_artifact(rejected)

    await service.collect_trajectories("ws-1", trajectory_dir)

    stored = {a.id: a.status for a in await metadata.list_artifacts()}
    assert stored == {artifact_id: ArtifactStatus.REJECTED}
    metadata.close()


# -- intent-driven growth ------------------------------------------------------


async def _drain(runtime) -> None:
    """Wait for the fire-and-forget sweep the intent scheduled.

    The sweep runs off the turn path, so the test has to let it finish before
    asserting on the store.
    """
    tasks = list(runtime._background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_evolution_intent_runs_a_sweep(tmp_path) -> None:
    """A recognised "learn from this" request must actually collect candidates.

    The router classifies the intent and publishes INTENT_EVOLUTION_REQUESTED;
    before this, nothing in the process subscribed, so the request was a dead
    end and an attached growth service never ran.
    """
    from Sprout.events import INTENT_EVOLUTION_REQUESTED
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None
    trajectory_dir = Path(settings.storage.trajectory_dir)
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    assert attach_evolution(runtime, settings) is not None
    assert await metadata.list_artifacts() == []

    await runtime.events.publish_simple(
        INTENT_EVOLUTION_REQUESTED,
        {"intent": "evolution", "workspace_id": "ws-1"},
    )
    await _drain(runtime)

    stored = await metadata.list_artifacts()
    assert stored, "the evolution intent produced no candidate"
    assert all(a.status is ArtifactStatus.VALIDATED for a in stored), (
        f"candidates were not evaluated: {[a.status.value for a in stored]}"
    )
    metadata.close()


@pytest.mark.asyncio
async def test_evolution_intent_without_workspace_does_nothing(tmp_path) -> None:
    """No workspace means no trajectories to read; the sweep must not blow up."""
    from Sprout.events import INTENT_EVOLUTION_REQUESTED
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None
    assert attach_evolution(runtime, settings) is not None

    await runtime.events.publish_simple(INTENT_EVOLUTION_REQUESTED, {"intent": "evolution"})

    assert await metadata.list_artifacts() == []
    metadata.close()


@pytest.mark.asyncio
async def test_evolution_intent_never_auto_publishes(tmp_path) -> None:
    """Collection stops at VALIDATED: publishing stays a human decision."""
    from Sprout.events import INTENT_EVOLUTION_REQUESTED
    from Sprout.evolution import attach_evolution

    runtime, settings = _wired_runtime(tmp_path)
    metadata = runtime.storage.metadata
    assert metadata is not None
    trajectory_dir = Path(settings.storage.trajectory_dir)
    recorder = JsonlTrajectoryRecorder(trajectory_dir / "task-1.jsonl")
    for name in ("node.completed", "node.failed", "task.failed"):
        await recorder.record(TrajectoryEvent(name=name, task_id="task-1"))

    assert attach_evolution(runtime, settings) is not None
    await runtime.events.publish_simple(
        INTENT_EVOLUTION_REQUESTED,
        {"intent": "evolution", "workspace_id": "ws-1"},
    )
    await _drain(runtime)

    stored = await metadata.list_artifacts()
    assert stored, "expected a candidate to collect"
    assert all(a.status is ArtifactStatus.VALIDATED for a in stored)
    assert not any(a.status is ArtifactStatus.PUBLISHED for a in stored)
    assert not any(s.trust == "trusted" for s in runtime.skills.list().values())
    metadata.close()

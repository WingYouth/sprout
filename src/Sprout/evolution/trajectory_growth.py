"""Trajectory-driven growth service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from Sprout.artifacts.models import Artifact, ArtifactStatus
from Sprout.events import EVOLUTION_PROPOSAL, EVOLUTION_SIGNAL, Event, EventBus
from Sprout.evolution.candidate import GrowthCandidateBuilder
from Sprout.evolution.candidate_evaluator import CandidateEvaluator
from Sprout.evolution.eligibility import LearningEligibilityFilter
from Sprout.evolution.models.evidence import EvidenceRef
from Sprout.evolution.models.signals import GrowthSignal
from Sprout.evolution.replay import ReplayCaseBuilder, ReplayEvaluator
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.trajectory.models import Trajectory, TrajectoryEvent, TrajectoryStatus
from Sprout.trajectory.recorder import JsonlTrajectoryRecorder

_FAILURE_EVENTS = {"agent.failed", "tool.failed", "node.failed", "task.failed"}

#: How many successful runs must share a node sequence before it counts as a
#: stable pattern. One run is not repetition; two can be coincidence. Three is
#: the smallest count where "this is how this kind of task goes here" is a
#: defensible claim, and it keeps the artifact from being minted on noise.
_MIN_REPEATS = 3

#: Statuses that encode a human (or terminal) decision. Re-collection must not
#: displace these: a rejected candidate stays rejected, a published skill keeps
#: its approved content rather than being rewritten by the next pass.
_DECIDED_STATUSES = frozenset(
    {
        ArtifactStatus.PUBLISHED,
        ArtifactStatus.MONITORING,
        ArtifactStatus.STABLE,
        ArtifactStatus.REJECTED,
        ArtifactStatus.DEPRECATED,
        ArtifactStatus.ROLLED_BACK,
    }
)


class TrajectorySignalExtractor:
    """Creates simple failure signals from trajectory events."""

    def extract(self, trajectory: Trajectory) -> list[GrowthSignal]:
        failures = [event for event in trajectory.events if event.name in _FAILURE_EVENTS]
        if not failures:
            return []
        count = len(failures)
        evidence = tuple(
            EvidenceRef(source_type="trajectory_event", source_id=event.id)
            for event in failures[:5]
        )
        signal = GrowthSignal(
            type="repeated_failure",
            title=f"Repeated failures in task {trajectory.task_id}",
            description=f"Observed {count} failure event(s) in trajectory {trajectory.id}.",
            evidence=evidence,
            confidence=min(0.9, 0.4 + 0.1 * count),
            impact_score=0.5,
            recurrence_score=min(1.0, count / 10),
            severity_score=0.5,
        )
        return [signal]


class StablePathExtractor:
    """Learns from runs that *worked*, not only from ones that failed.

    ``TrajectorySignalExtractor`` above reads a single trajectory and can only
    report "this failed". Stability is a claim about repetition, so it cannot
    be made from one run — this extractor takes a batch of successful
    trajectories and looks for the node sequence they share.

    The signals route to SKILL and WORKFLOW (``growth_router`` already knows
    those types; nothing produced them before), which is what the spec means by
    "the procedural knowledge of stable, repeated tasks".
    """

    def __init__(self, *, min_repeats: int = _MIN_REPEATS) -> None:
        self._min_repeats = max(2, min_repeats)

    def extract(self, trajectories: Sequence[Trajectory]) -> list[GrowthSignal]:
        successful = [
            trajectory
            for trajectory in trajectories
            if not any(event.name in _FAILURE_EVENTS for event in trajectory.events)
        ]
        if len(successful) < self._min_repeats:
            return []

        grouped: dict[tuple[str, ...], list[Trajectory]] = {}
        for trajectory in successful:
            path = self._node_path(trajectory)
            if path:
                grouped.setdefault(path, []).append(trajectory)

        signals: list[GrowthSignal] = []
        for path, members in grouped.items():
            if len(members) < self._min_repeats:
                continue
            signals.append(self._signal(path, members))
        return signals

    @staticmethod
    def _node_path(trajectory: Trajectory) -> tuple[str, ...]:
        """The node types this run visited, in order and deduplicated.

        Deduplicated because a resumed or retried graph revisits nodes — a
        live run showed ``evaluation`` and ``approval`` twice each — and the
        shape that matters is which stages the task went through, not how many
        attempts each took.
        """
        seen: list[str] = []
        for event in trajectory.events:
            if event.name != "node.started":
                continue
            node_type = str((event.payload or {}).get("type") or "")
            if node_type and (not seen or seen[-1] != node_type):
                seen.append(node_type)
        return tuple(dict.fromkeys(seen))

    def _signal(
        self, path: tuple[str, ...], members: Sequence[Trajectory]
    ) -> GrowthSignal:
        count = len(members)
        evidence = tuple(
            EvidenceRef(source_type="trajectory_event", source_id=event.id)
            for trajectory in members[:3]
            for event in trajectory.events[:2]
        )
        shape = " -> ".join(path)
        return GrowthSignal(
            type="behavior_pattern",
            title=f"Stable {len(path)}-stage path ({shape.split(' -> ')[0]}...)"
            if len(path) > 2
            else f"Stable path: {shape}",
            description=(
                f"{count} successful tasks followed the same node path: {shape}. "
                f"Treat it as the expected shape for this kind of work in this "
                f"workspace, so deviations stand out."
            ),
            evidence=evidence,
            confidence=min(0.9, 0.5 + 0.1 * (count - self._min_repeats + 1)),
            impact_score=0.4,
            recurrence_score=min(1.0, count / 10),
            severity_score=0.2,
        )


class TrajectoryGrowthService:
    """Collects eligible trajectories and turns them into growth candidates."""

    def __init__(
        self,
        metadata: MetadataStore,
        *,
        filter: LearningEligibilityFilter | None = None,
        extractor: TrajectorySignalExtractor | None = None,
        builder: GrowthCandidateBuilder | None = None,
        replay: ReplayEvaluator | None = None,
        evaluator: CandidateEvaluator | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._metadata = metadata
        self._filter = filter or LearningEligibilityFilter()
        self._extractor = extractor or TrajectorySignalExtractor()
        self._builder = builder or GrowthCandidateBuilder()
        self._replay = replay or ReplayEvaluator()
        self._evaluator = evaluator or CandidateEvaluator()
        self._stable_paths = StablePathExtractor()
        self._events = events

    async def collect(
        self,
        workspace_id: str,
        trajectory_dir: str | Path,
    ) -> list:
        candidates: list = []
        path = Path(trajectory_dir)
        if not path.exists():
            return candidates

        eligible: list[Trajectory] = []
        for file_path in sorted(path.glob("*.jsonl")):
            recorder = JsonlTrajectoryRecorder(file_path)
            events = await recorder.read_all()
            if not events:
                continue
            trajectory = self._trajectory_from_events(workspace_id, events)
            if self._filter.evaluate(trajectory).eligible:
                eligible.append(trajectory)

        # Failure signals are per-trajectory; stable-path signals need the
        # whole batch, which is why trajectories are gathered before either
        # extractor runs rather than processed file by file.
        for trajectory in eligible:
            for signal in self._extractor.extract(trajectory):
                candidates.extend(await self._materialize(signal, trajectory))

        for signal in self._stable_paths.extract(eligible):
            # Replay validates a candidate against exactly one trajectory and
            # requires *all* of its evidence to come from that one. A signal
            # drawn from a batch therefore has to be grounded in a single
            # representative run before it can be gated.
            origin = self._origin_for(signal, eligible)
            if origin is not None:
                grounded = self._ground(signal, origin)
                candidates.extend(await self._materialize(grounded, origin))

        return candidates

    @staticmethod
    def _ground(signal: GrowthSignal, trajectory: Trajectory) -> GrowthSignal:
        """Re-point a batch signal's evidence at one trajectory's events.

        Without this the candidate carries evidence from several runs, fails
        the replay check that every reference belongs to the trajectory under
        evaluation, and loses the 0.4 it needs to clear the gate.
        """
        in_trajectory = {event.id for event in trajectory.events}
        # Narrow to this run's events whenever any are missing: the replay
        # check requires *all* of a candidate's evidence to belong to the
        # trajectory under evaluation, so a signal carrying one foreign
        # reference scores zero on that check regardless of how many of its
        # own references are present.
        grounded = tuple(
            ref for ref in signal.evidence if ref.source_id in in_trajectory
        )
        if not grounded:
            grounded = tuple(
                EvidenceRef(source_type="trajectory_event", source_id=event.id)
                for event in trajectory.events
                if event.name == "node.started"
            )[:5]
        return replace(signal, evidence=grounded)

    async def _materialize(self, signal: GrowthSignal, trajectory: Trajectory) -> list:
        """Route a signal through replay and the hard gates, then persist it.

        Returns the accepted candidates so the caller can accumulate them;
        an empty list means the signal did not survive gating.
        """
        await self._emit(
            EVOLUTION_SIGNAL,
            {
                "signal_type": signal.type,
                "title": signal.title,
                "task_id": trajectory.task_id,
                "confidence": signal.confidence,
            },
        )
        candidate = self._builder.build(signal)
        replay_case = ReplayCaseBuilder().build(trajectory)
        if not self._replay.evaluate(candidate, replay_case, trajectory).passed:
            return []
        # Hard gates run before persistence and cannot be offset by utility.
        checks = self._replay.checks(trajectory)
        if not self._evaluator.evaluate(candidate, checks).passed:
            return []
        if candidate.artifact is not None:
            artifact = await self._reconcile(candidate.artifact)
            candidate = replace(candidate, artifact=artifact)
            await self._metadata.save_artifact(artifact)
            await self._emit(
                EVOLUTION_PROPOSAL,
                {
                    "artifact_id": artifact.id,
                    "kind": artifact.kind.value,
                    "name": artifact.name,
                    "task_id": trajectory.task_id,
                },
            )
        return [candidate]

    async def _reconcile(self, artifact: Artifact) -> Artifact:
        """Reuse the existing artifact for this name instead of minting a twin.

        Trajectory files are re-globbed on every pass, so the same signal is
        rebuilt each time — with a fresh ``uuid4`` id. The artifact ``name`` is
        the real dedup key, so an existing row wins: a second pass must not
        duplicate a candidate, and must never resurrect one a human already
        decided (``REJECTED``/``PUBLISHED``/deprecated).

        A decided artifact is returned untouched, which also means the replay
        gate's verdict does not overwrite the decision.
        """
        existing = await self._metadata.list_artifacts(artifact.name)
        if not existing:
            return artifact
        # list_artifacts(name) is ordered by version DESC; prefer a decided row
        # so re-collection can never displace a human decision, then the newest.
        decided = [
            item for item in existing if item.status in _DECIDED_STATUSES
        ]
        chosen = decided[0] if decided else existing[0]
        if chosen.status in _DECIDED_STATUSES:
            return chosen
        # Pending row: refresh its content and evidence, keep identity and status.
        return replace(
            artifact,
            id=chosen.id,
            status=chosen.status,
            created_at=chosen.created_at,
        )

    @staticmethod
    def _origin_for(
        signal: GrowthSignal, trajectories: Sequence[Trajectory]
    ) -> Trajectory | None:
        """The trajectory a batch signal was drawn from, for gating context.

        Replay evaluates one candidate against one trajectory, so a signal
        built from several needs a representative — the first whose events
        carry its evidence.
        """
        wanted = {ref.source_id for ref in signal.evidence}
        for trajectory in trajectories:
            if any(event.id in wanted for event in trajectory.events):
                return trajectory
        return None

    async def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self._events is not None:
            await self._events.publish(Event(name, payload))

    @staticmethod
    def _trajectory_from_events(
        workspace_id: str,
        events: list[TrajectoryEvent],
    ) -> Trajectory:
        task_id = events[0].task_id
        failed = any(event.name in _FAILURE_EVENTS for event in events)
        return Trajectory(
            task_id=task_id,
            workspace_id=workspace_id,
            status=TrajectoryStatus.FAILED if failed else TrajectoryStatus.COMPLETED,
            events=tuple(events),
        )

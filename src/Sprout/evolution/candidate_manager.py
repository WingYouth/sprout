"""Candidate lifecycle management."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from Sprout.artifacts.models import Artifact, ArtifactKind, ArtifactStatus, GrowthCandidate
from Sprout.events import EVOLUTION_PUBLISHED, SKILL_PUBLISHED, Event, EventBus
from Sprout.evolution.candidate_evaluator import CandidateEvaluator
from Sprout.runtime.state import ArtifactStateMachine
from Sprout.skills.models import Skill, TrustLevel
from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.contracts.metadata import MetadataStore

if TYPE_CHECKING:
    from Sprout.skills.registry import SkillRegistry
    from Sprout.skills.repository import SkillRepository
    from Sprout.storage.contracts.knowledge import KnowledgeStore


class CandidateManager:
    """Lists, evaluates, approves, and rejects new growth candidates."""

    def __init__(
        self,
        metadata: MetadataStore,
        *,
        skills: SkillRegistry | None = None,
        skill_repository: SkillRepository | None = None,
        knowledge: KnowledgeStore | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._metadata = metadata
        self._evaluator = CandidateEvaluator()
        self._skills = skills
        self._skill_repository = skill_repository
        self._knowledge = knowledge
        self._events = events

    async def list_candidates(self) -> list[GrowthCandidate]:
        artifacts = await self._metadata.list_artifacts()
        return [self._to_candidate(artifact) for artifact in artifacts]

    async def evaluate_all(self) -> dict[str, str]:
        changes: dict[str, str] = {}
        for candidate in await self.list_candidates():
            artifact = candidate.artifact
            if artifact is None or artifact.status is not ArtifactStatus.CANDIDATE:
                continue
            report = self._evaluator.evaluate(candidate)
            target = (
                ArtifactStatus.VALIDATED
                if report.passed
                else ArtifactStatus.REJECTED
            )
            ArtifactStateMachine.validate(artifact.status, target)
            updated = replace(
                artifact,
                status=target,
                updated_at=artifact.updated_at,
            )
            await self._metadata.save_artifact(updated)
            changes[artifact.id] = updated.status.value
        return changes

    async def approve(self, artifact_id: str, *, decided_by: str = "cli") -> Artifact:
        artifact = await self._require_artifact(artifact_id)
        if artifact.status not in {ArtifactStatus.VALIDATED, ArtifactStatus.PENDING_APPROVAL}:
            raise ValueError(
                f"Artifact {artifact.id} cannot be approved from {artifact.status.value}"
            )
        ArtifactStateMachine.validate(artifact.status, ArtifactStatus.PUBLISHED)
        updated = replace(
            artifact,
            status=ArtifactStatus.PUBLISHED,
            metadata={**artifact.metadata, "decided_by": decided_by},
        )
        await self._metadata.save_artifact(updated)
        await self._publish(updated)
        return updated

    async def reject(self, artifact_id: str, *, reason: str = "") -> Artifact:
        artifact = await self._require_artifact(artifact_id)
        if artifact.status not in {ArtifactStatus.VALIDATED, ArtifactStatus.PENDING_APPROVAL}:
            raise ValueError(
                f"Artifact {artifact.id} cannot be rejected from {artifact.status.value}"
            )
        ArtifactStateMachine.validate(artifact.status, ArtifactStatus.REJECTED)
        updated = replace(
            artifact,
            status=ArtifactStatus.REJECTED,
            metadata={**artifact.metadata, "rejection_reason": reason},
        )
        await self._metadata.save_artifact(updated)
        return updated

    async def mark_monitoring(self, artifact_id: str) -> Artifact:
        return await self._transition(
            artifact_id,
            allowed={ArtifactStatus.PUBLISHED},
            target=ArtifactStatus.MONITORING,
        )

    async def mark_stable(self, artifact_id: str) -> Artifact:
        return await self._transition(
            artifact_id,
            allowed={ArtifactStatus.MONITORING},
            target=ArtifactStatus.STABLE,
        )

    async def deprecate(self, artifact_id: str) -> Artifact:
        return await self._transition(
            artifact_id,
            allowed={ArtifactStatus.STABLE},
            target=ArtifactStatus.DEPRECATED,
        )

    async def _require_artifact(self, prefix: str) -> Artifact:
        for artifact in await self._metadata.list_artifacts():
            if artifact.id.startswith(prefix):
                return artifact
        raise LookupError(f"No artifact matches id prefix {prefix!r}")

    async def _transition(
        self,
        artifact_id: str,
        *,
        allowed: set[ArtifactStatus],
        target: ArtifactStatus,
    ) -> Artifact:
        artifact = await self._require_artifact(artifact_id)
        if artifact.status not in allowed:
            raise ValueError(
                f"Artifact {artifact.id} cannot transition from {artifact.status.value} "
                f"to {target.value}"
            )
        ArtifactStateMachine.validate(artifact.status, target)
        updated = replace(artifact, status=target)
        await self._metadata.save_artifact(updated)
        return updated

    @staticmethod
    def _to_candidate(artifact: Artifact) -> GrowthCandidate:
        return GrowthCandidate(
            artifact=artifact,
            evidence_ids=artifact.evidence_ids,
            diagnosis=str(artifact.metadata.get("diagnosis", "")),
            rationale=str(artifact.metadata.get("rationale", "")),
        )

    async def _publish(self, artifact: Artifact) -> None:
        if artifact.kind in (ArtifactKind.SKILL, ArtifactKind.WORKFLOW):
            # A workflow is "a mature repeated orchestration shape" — lessons
            # about how this workspace's tasks actually go. That reaches the
            # agent through the same channel as a skill, because both are
            # instruction text prepended to the prompt; the distinction the
            # spec draws is kept in ``artifacts.kind``, not in how it travels.
            #
            # Without this branch a workflow artifact was marked PUBLISHED and
            # nothing else happened: no consumer existed, so a learned pattern
            # could never influence the next task.
            # ``trust`` must be set explicitly: the dataclass default is
            # ``untrusted``, and ``AgentContext.visible_skills`` requires
            # ``trusted``, so leaving it off registered the skill but kept it
            # out of the prompt. Approving is the human decision that grants
            # trust — ``approve`` records ``decided_by`` — so this is the one
            # place a self-evolved skill may become injectable. It also makes
            # the in-memory registry agree with what the loader reports after a
            # restart, instead of flipping the other way.
            skill = Skill(
                name=artifact.name,
                version=artifact.version,
                instructions=artifact.content,
                required_tools=(),
                enabled=True,
                trust=TrustLevel.TRUSTED.value,
            )
            if self._skill_repository is not None:
                self._skill_repository.save(skill)
            if self._skills is not None:
                self._skills.register(skill)
            await self._emit(
                SKILL_PUBLISHED,
                {
                    "artifact_id": artifact.id,
                    "kind": artifact.kind.value,
                    "name": artifact.name,
                    "version": artifact.version,
                },
            )
        elif artifact.kind is ArtifactKind.PROJECT_KNOWLEDGE:
            if self._knowledge is None:
                raise ValueError("No KnowledgeStore configured for project knowledge publish")
            await self._knowledge.put(
                KnowledgeItem(
                    id=f"ka-{artifact.id}",
                    content=artifact.content,
                    kind="knowledge",
                    evidence_ids=artifact.evidence_ids,
                )
            )
        await self._emit(
            EVOLUTION_PUBLISHED,
            {
                "artifact_id": artifact.id,
                "kind": artifact.kind.value,
                "name": artifact.name,
                "version": artifact.version,
            },
        )

    async def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self._events is not None:
            await self._events.publish(Event(name, payload))

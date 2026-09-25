"""Artifact and growth candidate domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class ArtifactKind(StrEnum):
    SKILL = "skill"
    PROJECT_KNOWLEDGE = "project_knowledge"
    WORKFLOW = "workflow"
    ROUTING = "routing"
    PROMPT = "prompt"
    TOOL_PROPOSAL = "tool_proposal"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VALIDATING = "validating"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"
    MONITORING = "monitoring"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str = field(default_factory=lambda: str(uuid4()))
    kind: ArtifactKind = ArtifactKind.SKILL
    name: str = ""
    version: str = "0.1.0"
    content: str = ""
    status: ArtifactStatus = ArtifactStatus.DRAFT
    scope: str = "workspace"
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class GrowthCandidate:
    id: str = field(default_factory=lambda: str(uuid4()))
    artifact: Artifact | None = None
    evidence_ids: tuple[str, ...] = ()
    diagnosis: str = ""
    rationale: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

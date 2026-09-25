"""Immutable task trajectory and replay models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class TrajectoryStatus(StrEnum):
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    artifact_id: str
    artifact_version: str
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    task_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Trajectory:
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    workspace_id: str = ""
    workspace_revision: str | None = None
    status: TrajectoryStatus = TrajectoryStatus.RECORDING
    artifact_snapshots: tuple[ArtifactSnapshot, ...] = ()
    events: tuple[TrajectoryEvent, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ReplayCase:
    id: str = field(default_factory=lambda: str(uuid4()))
    trajectory_id: str = ""
    workspace_revision: str | None = None
    artifact_snapshot: ArtifactSnapshot | None = None
    fixed_scope: tuple[str, ...] = ()

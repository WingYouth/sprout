"""Core workspace domain objects.

These models are intentionally transport-free. Entry points and stores must
map their own records onto these objects instead of passing paths and dicts
through the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class WorkspaceKind(StrEnum):
    LOCAL_DIRECTORY = "local_directory"
    GIT_REPOSITORY = "git_repository"
    REMOTE = "remote"


class ResourceKind(StrEnum):
    PUBLIC = "public"
    SOURCE = "source"
    TEST = "test"
    CONFIG = "config"
    DOCUMENTATION = "documentation"
    DATA = "data"
    SENSITIVE = "sensitive"
    SECRET = "secret"
    EXTERNAL = "external"
    BINARY = "binary"
    OTHER = "other"


class WorkspaceGranularity(StrEnum):
    WORKSPACE = "workspace"
    PROJECT = "project"
    MODULE = "module"
    FILE = "file"
    SYMBOL = "symbol"
    REFERENCE = "reference"
    RUNTIME_ASSET = "runtime_asset"
    SKILL = "skill"


class ReadStage(StrEnum):
    DISCOVERY = "discovery"
    IDENTIFICATION = "identification"
    ANALYSIS = "analysis"
    TARGETED_READ = "targeted_read"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    workspace_id: str
    revision: str | None = None
    detected_languages: tuple[str, ...] = ()
    framework_hints: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()
    test_commands: tuple[str, ...] = ()
    build_commands: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    root: Path
    kind: WorkspaceKind = WorkspaceKind.LOCAL_DIRECTORY
    revision: str | None = None
    manifest: WorkspaceManifest | None = None


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    workspace_id: str
    name: str
    root: Path
    kind: str = "unknown"


@dataclass(frozen=True, slots=True)
class ResourceRef:
    workspace_id: str
    path: str
    revision: str | None = None
    content_hash: str | None = None
    kind: ResourceKind = ResourceKind.SOURCE


@dataclass(frozen=True, slots=True)
class ReadPlan:
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    purpose: str = ""
    resources: tuple[ResourceRef, ...] = ()
    excludes: tuple[str, ...] = ()
    stage: ReadStage = ReadStage.TARGETED_READ
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

"""Workspace analysis invalidation fingerprints."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from Sprout.workspace.models import ReadPlan, Workspace


@dataclass(frozen=True, slots=True)
class WorkspaceFingerprint:
    workspace_id: str
    revision: str | None = None
    resource_hashes: Mapping[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def compute(
        cls,
        workspace: Workspace,
        read_plan: ReadPlan,
    ) -> WorkspaceFingerprint:
        hashes: dict[str, str] = {}
        for resource in read_plan.resources:
            path = Path(workspace.root) / resource.path
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = ""
            hashes[resource.path] = digest
        return cls(
            workspace_id=workspace.id,
            revision=workspace.revision,
            resource_hashes=hashes,
        )

    def changed_resources(
        self,
        previous: WorkspaceFingerprint | None,
    ) -> tuple[str, ...]:
        if previous is None:
            return tuple(self.resource_hashes)
        if self.revision != previous.revision:
            return tuple(self.resource_hashes)
        changed: list[str] = []
        for path, digest in self.resource_hashes.items():
            if previous.resource_hashes.get(path) != digest:
                changed.append(path)
        for path in previous.resource_hashes:
            if path not in self.resource_hashes:
                changed.append(path)
        return tuple(changed)

    def is_stale(self, previous: WorkspaceFingerprint | None) -> bool:
        return bool(self.changed_resources(previous))


__all__ = ["WorkspaceFingerprint"]

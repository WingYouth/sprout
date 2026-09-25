"""Long-term artifact maintenance."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from Sprout.artifacts.models import ArtifactStatus
from Sprout.storage.contracts.metadata import MetadataStore


class ArtifactMaintenance:
    """Automatically advances artifacts based on age and status."""

    async def maintain(
        self,
        metadata: MetadataStore,
        *,
        stable_after_seconds: float = 86400.0,
        deprecate_after_seconds: float = 604800.0,
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        changes: dict[str, str] = {}
        for artifact in await metadata.list_artifacts():
            age = (now - artifact.updated_at).total_seconds()
            if artifact.status is ArtifactStatus.MONITORING and age >= deprecate_after_seconds:
                updated = replace(artifact, status=ArtifactStatus.DEPRECATED)
            elif artifact.status is ArtifactStatus.MONITORING and age >= stable_after_seconds:
                updated = replace(artifact, status=ArtifactStatus.STABLE)
            elif artifact.status is ArtifactStatus.STABLE and age >= deprecate_after_seconds:
                updated = replace(artifact, status=ArtifactStatus.DEPRECATED)
            else:
                continue
            await metadata.save_artifact(updated)
            changes[artifact.id] = updated.status.value
        return changes

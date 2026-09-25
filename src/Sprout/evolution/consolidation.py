"""Backward consolidation for versioned growth artifacts."""

from __future__ import annotations

from dataclasses import replace

from Sprout.artifacts.models import Artifact, ArtifactStatus
from Sprout.storage.contracts.metadata import MetadataStore

#: Statuses consolidation leaves alone. A PUBLISHED artifact is a human
#: decision (``approve`` records ``decided_by``), so a newer same-name
#: candidate must never deprecate it: collection re-mints a duplicate on every
#: pass, and without this exemption each pass silently retired the live skill.
_PROTECTED = frozenset(
    {
        ArtifactStatus.PUBLISHED,
        ArtifactStatus.DEPRECATED,
        ArtifactStatus.REJECTED,
        ArtifactStatus.ROLLED_BACK,
    }
)


class ArtifactConsolidator:
    """Deprecates older versions of the same artifact name."""

    async def consolidate(self, metadata: MetadataStore) -> dict[str, str]:
        artifacts = await metadata.list_artifacts()
        by_name: dict[str, list[Artifact]] = {}
        for artifact in artifacts:
            by_name.setdefault(artifact.name, []).append(artifact)

        changes: dict[str, str] = {}
        for items in by_name.values():
            if len(items) < 2:
                continue
            items.sort(key=lambda item: item.updated_at, reverse=True)
            for old in items[1:]:
                if old.status in _PROTECTED:
                    continue
                updated = replace(old, status=ArtifactStatus.DEPRECATED)
                await metadata.save_artifact(updated)
                changes[old.id] = updated.status.value
        return changes

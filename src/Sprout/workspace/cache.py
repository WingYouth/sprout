"""In-memory cache for WorkspaceAnalysis objects with an optional hot lane.

The full analysis object stays in memory because it contains graphs and
knowledge items that do not round-trip through JSON cleanly. When a cache
store is configured, a compact fingerprint snapshot is mirrored there so a
later process (or an operator) can see what revision was last analyzed and how
large the derived data was, without re-scanning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from Sprout.workspace.serialization import from_jsonable, to_jsonable

if TYPE_CHECKING:
    from Sprout.storage.contracts.cache import CacheStore
    from Sprout.workspace.intelligence import WorkspaceAnalysis


@dataclass(slots=True)
class WorkspaceAnalysisCache:
    cache_store: CacheStore | None = None
    key_prefix: str = "sprout:workspace:analysis:"
    _entries: dict[str, WorkspaceAnalysis] = field(default_factory=dict)

    async def get(self, workspace_id: str) -> WorkspaceAnalysis | None:
        """Return the cached analysis from memory, or the hot lane, or None."""
        if workspace_id in self._entries:
            return self._entries[workspace_id]
        if self.cache_store is None:
            return None
        raw = await self.cache_store.get(self._key(workspace_id))
        if raw is None:
            return None
        try:
            from Sprout.workspace.intelligence import WorkspaceAnalysis

            return from_jsonable(raw, WorkspaceAnalysis)
        except Exception:  # noqa: BLE001 - a stale/unreadable snapshot is a miss
            return None

    def put(self, workspace_id: str, analysis: WorkspaceAnalysis) -> None:
        self._entries[workspace_id] = analysis

    def _key(self, workspace_id: str) -> str:
        return f"{self.key_prefix}{workspace_id}"

    async def persist(
        self,
        workspace_id: str,
        analysis: WorkspaceAnalysis,
    ) -> None:
        """Mirror the full analysis snapshot into the hot lane."""
        if self.cache_store is None:
            return
        await self.cache_store.set(self._key(workspace_id), to_jsonable(analysis))

    async def forget(self, workspace_id: str | None = None) -> None:
        """Drop the hot-lane mirror for one workspace or all workspaces."""
        if self.cache_store is None:
            return
        if workspace_id is None:
            # The cache-store contract has no scan/clear-all; invalidating the
            # in-memory map already covers the current process, and the hot
            # mirrors are keyed so stale entries are simply overwritten later.
            return
        await self.cache_store.delete(self._key(workspace_id))

    def invalidate(self, workspace_id: str | None = None) -> None:
        if workspace_id is None:
            self._entries.clear()
            return
        self._entries.pop(workspace_id, None)


__all__ = ["WorkspaceAnalysisCache"]

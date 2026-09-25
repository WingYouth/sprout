"""Workspace registration, scanning, and read planning.

The service owns workspace persistence so the Runtime stays a thin coordinator
(Herness spec 12): registering a root, scanning a manifest, and building the
bounded read plan a task is allowed to touch.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from Sprout.storage.bundle import StorageBundle
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.task.models import Task
from Sprout.workspace.cache import WorkspaceAnalysisCache
from Sprout.workspace.intelligence import WorkspaceAnalysis, WorkspaceIntelligence
from Sprout.workspace.models import (
    ReadPlan,
    Workspace,
    WorkspaceKind,
    WorkspaceManifest,
)
from Sprout.workspace.scanner import WorkspaceScanner


class WorkspaceService:
    """Registers workspaces and builds the read plans that bound a task."""

    def __init__(
        self,
        storage: StorageBundle,
        scanner: WorkspaceScanner | None = None,
        skills_dir: str | None = None,
    ) -> None:
        self._storage = storage
        self._scanner = scanner or WorkspaceScanner()
        self._intelligence = WorkspaceIntelligence(
            scanner=self._scanner,
            knowledge_store=storage.knowledge,
            vector_store=storage.vectors,
            skills_dir=skills_dir,
            graph_store=storage.graph,
        )
        self._analysis_cache = WorkspaceAnalysisCache(
            cache_store=storage.cache,
        )

    @property
    def _metadata(self) -> MetadataStore:
        metadata = self._storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        return metadata

    async def open(
        self,
        root: str | Path,
        *,
        workspace_id: str | None = None,
    ) -> Workspace:
        """Register a local or Git workspace in the metadata store."""
        path = Path(root).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Workspace path does not exist: {path}")
        if workspace_id is None:
            existing = await self._metadata.list_workspaces()
            for item in existing:
                if Path(item.root).resolve() == path:
                    return item
        workspace = Workspace(
            id=workspace_id or str(uuid4()),
            root=path,
            kind=(
                WorkspaceKind.GIT_REPOSITORY
                if (path / ".git").exists()
                else WorkspaceKind.LOCAL_DIRECTORY
            ),
        )
        await self._metadata.save_workspace(workspace)
        return workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        return await self._metadata.get_workspace(workspace_id)

    async def list(self) -> list[Workspace]:
        workspaces = await self._metadata.list_workspaces()
        unique: dict[Path, Workspace] = {}
        for workspace in workspaces:
            unique.setdefault(Path(workspace.root).resolve(), workspace)
        return list(unique.values())

    async def scan(self, workspace_id: str) -> WorkspaceManifest:
        """Scan a workspace and persist its manifest."""
        workspace = await self.get(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {workspace_id}")
        manifest = self._scanner.scan(workspace)
        await self._metadata.save_workspace(
            Workspace(
                id=workspace.id,
                root=workspace.root,
                kind=workspace.kind,
                revision=workspace.revision,
                manifest=manifest,
            )
        )
        return manifest

    async def read_plan(self, task_id: str) -> ReadPlan:
        """Build the read plan for a task, scanning its workspace first."""
        task = await self._metadata.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        workspace = await self.get(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")
        manifest = await self.scan(workspace.id)
        return self._scanner.build_read_plan(
            Workspace(
                id=workspace.id,
                root=workspace.root,
                kind=workspace.kind,
                revision=workspace.revision,
                manifest=manifest,
            ),
            task,
        )

    async def analyze(
        self,
        workspace_id: str,
        *,
        task_id: str | None = None,
    ) -> WorkspaceAnalysis:
        """Build manifest, read plan, graph, and project knowledge together."""
        workspace = await self.get(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {workspace_id}")

        task = None
        if task_id is not None:
            task = await self._metadata.get_task(task_id)
            if task is None:
                raise LookupError(f"Task not found: {task_id}")
        task = task or Task(
            workspace_id=workspace.id,
            instruction="understand project",
            source="workspace",
        )

        previous = await self._analysis_cache.get(workspace.id)
        analysis = await self._intelligence.analyze(
            workspace,
            task,
            previous=previous,
        )
        self._analysis_cache.put(workspace.id, analysis)
        await self._analysis_cache.persist(workspace.id, analysis)
        await self._metadata.save_workspace(analysis.workspace)
        return analysis

    async def invalidate_workspace(self, workspace_id: str | None = None) -> None:
        """Drop cached workspace analyses for one workspace or all workspaces."""
        self._analysis_cache.invalidate(workspace_id)
        await self._analysis_cache.forget(workspace_id)

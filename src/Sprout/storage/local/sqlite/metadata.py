"""SQLite implementation of the SEMA MetadataStore."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from Sprout.artifacts.models import Artifact, ArtifactKind, ArtifactStatus
from Sprout.execution.models import (
    ChangeProposal,
    ChangeProposalStatus,
    DiffResult,
    SandboxRef,
    TestResult,
)
from Sprout.gateway.identity import Principal
from Sprout.orchestration.models import (
    DataRef,
    ExecutionNode,
    NodeBudget,
    NodeStatus,
    NodeType,
)
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas
from Sprout.task.models import (
    DelegationScope,
    Task,
    TaskBudget,
    TaskStatus,
)
from Sprout.trajectory.models import ArtifactSnapshot, Trajectory, TrajectoryStatus
from Sprout.workspace.models import (
    Workspace,
    WorkspaceKind,
    WorkspaceManifest,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    kind TEXT NOT NULL,
    revision TEXT,
    manifest_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    instruction TEXT NOT NULL,
    actor_json TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    delegation_scope_json TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    phases_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS execution_nodes (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    type TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    budget_json TEXT NOT NULL,
    result_ref_json TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_task ON execution_nodes(task_id, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_name ON artifacts(name, version);

CREATE TABLE IF NOT EXISTS trajectories (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workspace_revision TEXT,
    status TEXT NOT NULL,
    artifact_snapshots_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trajectories_task ON trajectories(task_id, created_at);

CREATE TABLE IF NOT EXISTS change_proposals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    sandbox_json TEXT,
    files_changed_json TEXT NOT NULL,
    test_results_json TEXT NOT NULL,
    diffs_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    required_capability_diff_json TEXT NOT NULL,
    rollback_plan TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_proposals_task ON change_proposals(task_id, created_at);
"""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class SqliteMetadataStore:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- workspaces ---------------------------------------------------------
    async def save_workspace(self, workspace: Workspace) -> None:
        manifest = workspace.manifest
        manifest_data = {
            "workspace_id": manifest.workspace_id,
            "revision": manifest.revision,
            "detected_languages": list(manifest.detected_languages),
            "framework_hints": list(manifest.framework_hints),
            "entry_points": list(manifest.entry_points),
            "test_commands": list(manifest.test_commands),
            "build_commands": list(manifest.build_commands),
            "created_at": manifest.created_at.isoformat(),
        } if manifest is not None else {}
        await self._db.execute(
            "INSERT OR REPLACE INTO workspaces "
            "(id, root, kind, revision, manifest_json) VALUES (?, ?, ?, ?, ?)",
            (
                workspace.id,
                str(workspace.root),
                workspace.kind.value,
                workspace.revision,
                _json_dumps(manifest_data),
            ),
        )

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        row = await self._db.fetchone(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        )
        return self._row_to_workspace(row) if row else None

    async def list_workspaces(self) -> list[Workspace]:
        rows = await self._db.fetchall("SELECT * FROM workspaces ORDER BY id")
        return [self._row_to_workspace(row) for row in rows]

    @staticmethod
    def _row_to_workspace(row: Any) -> Workspace:
        manifest_data = _json_loads(row["manifest_json"], {})
        manifest = None
        if manifest_data:
            manifest = WorkspaceManifest(
                workspace_id=manifest_data["workspace_id"],
                revision=manifest_data.get("revision"),
                detected_languages=tuple(manifest_data.get("detected_languages", ())),
                framework_hints=tuple(manifest_data.get("framework_hints", ())),
                entry_points=tuple(manifest_data.get("entry_points", ())),
                test_commands=tuple(manifest_data.get("test_commands", ())),
                build_commands=tuple(manifest_data.get("build_commands", ())),
                created_at=datetime.fromisoformat(manifest_data["created_at"]),
            )
        return Workspace(
            id=row["id"],
            root=Path(row["root"]),
            kind=WorkspaceKind(row["kind"]),
            revision=row["revision"],
            manifest=manifest,
        )

    # -- tasks --------------------------------------------------------------
    async def save_task(self, task: Task) -> None:
        actor = {
            "user_id": task.actor.user_id,
            "display_name": task.actor.display_name,
            "roles": list(task.actor.roles),
        }
        scope = {
            "allowed_actions": sorted(task.delegation_scope.allowed_actions),
            "denied_actions": sorted(task.delegation_scope.denied_actions),
            "allowed_paths": list(task.delegation_scope.allowed_paths),
            "denied_paths": list(task.delegation_scope.denied_paths),
        }
        budget = {
            "max_tokens": task.budget.max_tokens,
            "max_model_calls": task.budget.max_model_calls,
            "max_tool_calls": task.budget.max_tool_calls,
            "max_duration_seconds": task.budget.max_duration_seconds,
            "max_cost_usd": task.budget.max_cost_usd,
        }
        await self._db.execute(
            "INSERT OR REPLACE INTO tasks "
            "(id, workspace_id, instruction, actor_json, source, status, "
            "delegation_scope_json, budget_json, phases_json, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.workspace_id,
                task.instruction,
                _json_dumps(actor),
                task.source,
                task.status.value,
                _json_dumps(scope),
                _json_dumps(budget),
                _json_dumps([phase.value for phase in task.phases]),
                _json_dumps(dict(task.metadata)),
                task.created_at.isoformat(),
            ),
        )

    async def get_task(self, task_id: str) -> Task | None:
        row = await self._db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self._row_to_task(row) if row else None

    async def list_tasks(self, workspace_id: str | None = None) -> list[Task]:
        if workspace_id is None:
            rows = await self._db.fetchall("SELECT * FROM tasks ORDER BY created_at DESC")
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM tasks WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            )
        return [self._row_to_task(row) for row in rows]

    async def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        await self._db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?", (status.value, task_id)
        )

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        actor = _json_loads(row["actor_json"], {})
        scope = _json_loads(row["delegation_scope_json"], {})
        budget = _json_loads(row["budget_json"], {})
        phases = _json_loads(row["phases_json"], [])
        from Sprout.task.models import Phase

        return Task(
            id=row["id"],
            workspace_id=row["workspace_id"],
            instruction=row["instruction"],
            actor=Principal(
                user_id=actor.get("user_id", "system"),
                display_name=actor.get("display_name"),
                roles=tuple(actor.get("roles", ())),
            ),
            source=row["source"],
            status=TaskStatus(row["status"]),
            delegation_scope=DelegationScope(
                allowed_actions=frozenset(scope.get("allowed_actions", ())),
                denied_actions=frozenset(scope.get("denied_actions", ())),
                allowed_paths=tuple(scope.get("allowed_paths", ())),
                denied_paths=tuple(scope.get("denied_paths", ())),
            ),
            budget=TaskBudget(**budget),
            phases=tuple(Phase(value) for value in phases),
            metadata=dict(_json_loads(row["metadata_json"], {})),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- execution nodes ----------------------------------------------------
    async def save_execution_node(self, node: ExecutionNode) -> None:
        budget = {
            "max_attempts": node.budget.max_attempts,
            "timeout_seconds": node.budget.timeout_seconds,
            "max_tokens": node.budget.max_tokens,
        }
        result_ref = None
        if node.result_ref is not None:
            result_ref = {
                "id": node.result_ref.id,
                "store": node.result_ref.store,
                "key": node.result_ref.key,
                "content_hash": node.result_ref.content_hash,
            }
        await self._db.execute(
            "INSERT OR REPLACE INTO execution_nodes "
            "(id, task_id, type, dependencies_json, status, attempts, budget_json, "
            "result_ref_json, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node.id,
                node.task_id,
                node.type.value,
                _json_dumps(list(node.dependencies)),
                node.status.value,
                node.attempts,
                _json_dumps(budget),
                _json_dumps(result_ref) if result_ref is not None else None,
                _json_dumps(dict(node.metadata)),
                node.created_at.isoformat(),
            ),
        )

    async def get_execution_node(self, node_id: str) -> ExecutionNode | None:
        row = await self._db.fetchone(
            "SELECT * FROM execution_nodes WHERE id = ?", (node_id,)
        )
        return self._row_to_execution_node(row) if row else None

    async def list_execution_nodes(self, task_id: str) -> list[ExecutionNode]:
        rows = await self._db.fetchall(
            "SELECT * FROM execution_nodes WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )
        return [self._row_to_execution_node(row) for row in rows]

    @staticmethod
    def _row_to_execution_node(row: Any) -> ExecutionNode:
        budget = _json_loads(row["budget_json"], {})
        result_data = _json_loads(row["result_ref_json"], None)
        result_ref = None
        if result_data:
            result_ref = DataRef(
                id=result_data["id"],
                store=result_data.get("store", "blob"),
                key=result_data.get("key", ""),
                content_hash=result_data.get("content_hash"),
            )
        return ExecutionNode(
            id=row["id"],
            task_id=row["task_id"],
            type=NodeType(row["type"]),
            dependencies=tuple(_json_loads(row["dependencies_json"], [])),
            status=NodeStatus(row["status"]),
            attempts=int(row["attempts"]),
            budget=NodeBudget(**budget),
            result_ref=result_ref,
            metadata=dict(_json_loads(row["metadata_json"], {})),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- artifacts ----------------------------------------------------------
    async def save_artifact(self, artifact: Artifact) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO artifacts "
            "(id, kind, name, version, content, status, scope, evidence_json, "
            "metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.id,
                artifact.kind.value,
                artifact.name,
                artifact.version,
                artifact.content,
                artifact.status.value,
                artifact.scope,
                _json_dumps(list(artifact.evidence_ids)),
                _json_dumps(dict(artifact.metadata)),
                artifact.created_at.isoformat(),
                artifact.updated_at.isoformat(),
            ),
        )

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = await self._db.fetchone(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        )
        return self._row_to_artifact(row) if row else None

    async def list_artifacts(self, name: str | None = None) -> list[Artifact]:
        if name is None:
            rows = await self._db.fetchall(
                "SELECT * FROM artifacts ORDER BY updated_at DESC"
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM artifacts WHERE name = ? ORDER BY version DESC", (name,)
            )
        return [self._row_to_artifact(row) for row in rows]

    @staticmethod
    def _row_to_artifact(row: Any) -> Artifact:
        return Artifact(
            id=row["id"],
            kind=ArtifactKind(row["kind"]),
            name=row["name"],
            version=row["version"],
            content=row["content"],
            status=ArtifactStatus(row["status"]),
            scope=row["scope"],
            evidence_ids=tuple(_json_loads(row["evidence_json"], [])),
            metadata=dict(_json_loads(row["metadata_json"], {})),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # -- change proposals --------------------------------------------------
    async def save_change_proposal(self, proposal: ChangeProposal) -> None:
        sandbox_data = None
        if proposal.sandbox_ref is not None:
            sandbox_data = {
                "id": proposal.sandbox_ref.id,
                "kind": proposal.sandbox_ref.kind,
                "root": str(proposal.sandbox_ref.root),
                "worktree_ref": proposal.sandbox_ref.worktree_ref,
            }
        test_data = [
            {
                "name": item.name,
                "passed": item.passed,
                "output": item.output,
                "duration_ms": item.duration_ms,
                # Must persist, or the apply gate cannot tell a withheld
                # command from a failed one once the proposal is read back.
                "executed": item.executed,
            }
            for item in proposal.test_results
        ]
        diff_data = [
            {
                "path": item.path,
                "diff_text": item.diff_text,
                "old_hash": item.old_hash,
                "new_hash": item.new_hash,
            }
            for item in proposal.diffs
        ]
        await self._db.execute(
            "INSERT OR REPLACE INTO change_proposals "
            "(id, task_id, sandbox_json, files_changed_json, test_results_json, "
            "diffs_json, risk, required_capability_diff_json, rollback_plan, status, "
            "metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.id,
                proposal.task_id,
                _json_dumps(sandbox_data) if sandbox_data is not None else None,
                _json_dumps(list(proposal.files_changed)),
                _json_dumps(test_data),
                _json_dumps(diff_data),
                proposal.risk,
                _json_dumps(list(proposal.required_capability_diff)),
                proposal.rollback_plan,
                proposal.status.value,
                _json_dumps(dict(proposal.metadata)),
                proposal.created_at.isoformat(),
            ),
        )

    async def get_change_proposal(self, proposal_id: str) -> ChangeProposal | None:
        row = await self._db.fetchone(
            "SELECT * FROM change_proposals WHERE id = ?", (proposal_id,)
        )
        return self._row_to_change_proposal(row) if row else None

    async def list_change_proposals(self, task_id: str) -> list[ChangeProposal]:
        rows = await self._db.fetchall(
            "SELECT * FROM change_proposals WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        )
        return [self._row_to_change_proposal(row) for row in rows]

    @staticmethod
    def _row_to_change_proposal(row: Any) -> ChangeProposal:
        sandbox_data = _json_loads(row["sandbox_json"], None)
        sandbox_ref = None
        if sandbox_data:
            sandbox_ref = SandboxRef(
                id=sandbox_data["id"],
                kind=sandbox_data["kind"],
                root=sandbox_data["root"],
                worktree_ref=sandbox_data.get("worktree_ref"),
            )
        tests = _json_loads(row["test_results_json"], [])
        diffs = _json_loads(row["diffs_json"], [])
        return ChangeProposal(
            id=row["id"],
            task_id=row["task_id"],
            sandbox_ref=sandbox_ref,
            files_changed=tuple(_json_loads(row["files_changed_json"], [])),
            test_results=tuple(
                TestResult(
                    name=item["name"],
                    passed=bool(item["passed"]),
                    output=item.get("output", ""),
                    duration_ms=float(item.get("duration_ms", 0.0)),
                    # Absent means a row written before withheld commands
                    # existed, which always executed.
                    executed=bool(item.get("executed", True)),
                )
                for item in tests
            ),
            diffs=tuple(
                DiffResult(
                    path=item["path"],
                    diff_text=item.get("diff_text", ""),
                    old_hash=item.get("old_hash"),
                    new_hash=item.get("new_hash"),
                )
                for item in diffs
            ),
            risk=row["risk"],
            required_capability_diff=tuple(
                _json_loads(row["required_capability_diff_json"], [])
            ),
            rollback_plan=row["rollback_plan"],
            status=ChangeProposalStatus(row["status"]),
            metadata=dict(_json_loads(row["metadata_json"], {})),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- trajectory metadata ------------------------------------------------
    async def save_trajectory_metadata(self, trajectory: Trajectory) -> None:
        snapshots = [
            {
                "artifact_id": item.artifact_id,
                "artifact_version": item.artifact_version,
                "content_hash": item.content_hash,
            }
            for item in trajectory.artifact_snapshots
        ]
        await self._db.execute(
            "INSERT OR REPLACE INTO trajectories "
            "(id, task_id, workspace_id, workspace_revision, status, "
            "artifact_snapshots_json, metrics_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trajectory.id,
                trajectory.task_id,
                trajectory.workspace_id,
                trajectory.workspace_revision,
                trajectory.status.value,
                _json_dumps(snapshots),
                _json_dumps(dict(trajectory.metrics)),
                trajectory.created_at.isoformat(),
            ),
        )

    async def get_trajectory_metadata(self, trajectory_id: str) -> Trajectory | None:
        row = await self._db.fetchone(
            "SELECT * FROM trajectories WHERE id = ?", (trajectory_id,)
        )
        if row is None:
            return None
        snapshots = _json_loads(row["artifact_snapshots_json"], [])
        return Trajectory(
            id=row["id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            workspace_revision=row["workspace_revision"],
            status=TrajectoryStatus(row["status"]),
            artifact_snapshots=tuple(
                ArtifactSnapshot(
                    artifact_id=item["artifact_id"],
                    artifact_version=item["artifact_version"],
                    content_hash=item.get("content_hash"),
                )
                for item in snapshots
            ),
            metrics=dict(_json_loads(row["metrics_json"], {})),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def open_metadata_store(
    path: str, pragmas: SqlitePragmas | None = None
) -> SqliteMetadataStore:
    """Open and reserve a SEMA metadata database."""
    return SqliteMetadataStore(SqliteDatabase.open(path, pragmas))

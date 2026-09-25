"""Tests for sandbox cleanup and deterministic graph construction."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from Sprout.execution.models import ChangeProposal, SandboxRef
from Sprout.orchestration.compiler import ExecutionGraphBuilder
from Sprout.orchestration.models import ExecutionNode, NodeType
from Sprout.sandbox.git_worktree import GitWorktreeSandbox
from Sprout.sandbox.lifecycle import SandboxLifecycleService
from Sprout.task.models import Task, TaskResult, TaskStatus
from Sprout.workspace.models import ReadPlan, Workspace, WorkspaceKind, WorkspaceManifest


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "Test User")
    _run_git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _workspace(repo: Path) -> Workspace:
    return Workspace(
        id="workspace-1",
        root=repo,
        kind=WorkspaceKind.GIT_REPOSITORY,
    )


class _FakeMetadata:
    def __init__(
        self,
        *,
        workspace: Workspace,
        proposals: tuple[ChangeProposal, ...] = (),
        tasks: tuple[Task, ...] = (),
        nodes: tuple[ExecutionNode, ...] = (),
    ) -> None:
        self._workspace = workspace
        self._proposals = proposals
        self._tasks = tasks
        self._nodes = nodes

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self._workspace if workspace_id == self._workspace.id else None

    async def list_workspaces(self) -> list[Workspace]:
        return [self._workspace]

    async def list_tasks(self) -> list[Task]:
        return list(self._tasks)

    async def get_task(self, task_id: str) -> Task | None:
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    async def list_change_proposals(self, task_id: str) -> list[ChangeProposal]:
        return [
            proposal
            for proposal in self._proposals
            if proposal.task_id == task_id
        ]

    async def list_execution_nodes(self, task_id: str) -> list[ExecutionNode]:
        return [
            node for node in self._nodes if node.task_id == task_id
        ]


def _task() -> Task:
    return Task(
        id="task-1",
        workspace_id="workspace-1",
        instruction="test",
        source="test",
    )


def test_worktree_remove_deletes_worktree_and_branch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        assert ref.root.exists()
        assert _run_git(repo, "branch", "--list", ref.worktree_ref or "")

        await sandbox.remove(ref)
        assert not ref.root.exists()
        assert not _run_git(repo, "branch", "--list", ref.worktree_ref or "")

    asyncio.run(run())


def test_worktree_remove_rejects_unsafe_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    unsafe = tmp_path.parent / ".sprout-not-ours"

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = SandboxRef(
            id="unsafe",
            kind="git_worktree",
            root=unsafe,
            worktree_ref="sprout-sandbox-unsafe",
        )
        try:
            await sandbox.remove(ref)
        except ValueError as exc:
            assert "outside the workspace parent" in str(exc)
        else:
            raise AssertionError("unsafe sandbox root was accepted")

    asyncio.run(run())


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.ROLLED_BACK,
    ],
)
def test_lifecycle_finalize_removes_terminal_task_sandbox(
    tmp_path: Path, status: TaskStatus
) -> None:
    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        task = _task()
        proposal = ChangeProposal(
            task_id=task.id,
            sandbox_ref=ref,
        )
        metadata = _FakeMetadata(
            workspace=_workspace(repo),
            proposals=(proposal,),
            tasks=(task,),
        )
        service = SandboxLifecycleService(metadata)

        await service.finalize(
            task,
            TaskResult(task_id=task.id, status=status),
        )
        assert not ref.root.exists()
        assert not _run_git(repo, "branch", "--list", ref.worktree_ref or "")

    asyncio.run(run())


def test_reconcile_removes_unreferenced_worktree(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        metadata = _FakeMetadata(workspace=_workspace(repo))
        service = SandboxLifecycleService(metadata)

        await service.reconcile_orphans()
        assert not ref.root.exists()

    asyncio.run(run())


def test_reconcile_keeps_a_waiting_approval_task_sandbox(tmp_path: Path) -> None:
    """A parked evaluation has no proposal yet, but its sandbox is still live."""
    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        task = replace(_task(), status=TaskStatus.WAITING_APPROVAL)
        node = ExecutionNode(
            id=f"{task.id}:sandbox",
            task_id=task.id,
            type=NodeType.SANDBOX,
            metadata={"output": {"root": str(ref.root)}},
        )
        metadata = _FakeMetadata(
            workspace=_workspace(repo),
            tasks=(task,),
            nodes=(node,),
        )
        service = SandboxLifecycleService(metadata)

        await service.reconcile_orphans()
        assert ref.root.exists()

    asyncio.run(run())


def test_changed_files_ignores_bytecode_caches(tmp_path: Path) -> None:
    """A proposal must not offer to commit ``__pycache__``.

    Regression: the change set came from raw ``git status``, so every ``.pyc``
    the verification step produced read as an agent edit. It is not an edit —
    it is a byproduct of running the tests *inside* the sandbox — and it reached
    the approver as a file in the proposed commit. A repository that ignores its
    caches (``.gitignore``) hid this; one that does not, which is exactly the
    project a task is most likely to be pointed at, did not.
    """

    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        # What running pytest in the sandbox leaves behind.
        (ref.root / "pkg" / "__pycache__").mkdir(parents=True)
        (ref.root / "pkg" / "__pycache__" / "mod.cpython-314.pyc").write_bytes(b"\x00")
        (ref.root / ".pytest_cache").mkdir()
        (ref.root / ".pytest_cache" / "CACHEDIR.TAG").write_text("x", encoding="utf-8")
        # ...and a real edit, which must survive the filter.
        (ref.root / "pkg").mkdir(exist_ok=True)
        (ref.root / "pkg" / "mod.py").write_text("value = 1\n", encoding="utf-8")

        changed = await sandbox.changed_files(ref)
        await sandbox.remove(ref)

        assert "pkg/mod.py" in changed, "the real edit was filtered out with the caches"
        caches = [path for path in changed if "pycache" in path or path.endswith(".pyc")]
        assert not caches, f"bytecode caches reached the change set: {caches}"

    asyncio.run(run())


def test_diff_ignores_bytecode_caches(tmp_path: Path) -> None:
    """The same leak through the diff, which is what actually gets committed."""
    repo = _git_repo(tmp_path)

    async def run() -> None:
        sandbox = GitWorktreeSandbox(_workspace(repo))
        ref = await sandbox.create()
        (ref.root / "__pycache__").mkdir()
        (ref.root / "__pycache__" / "mod.cpython-314.pyc").write_bytes(b"\x00")
        (ref.root / "mod.py").write_text("value = 1\n", encoding="utf-8")

        diff = await sandbox.diff(ref)
        await sandbox.remove(ref)

        assert "mod.py" in diff.diff_text, "the real edit is missing from the diff"
        assert "pycache" not in diff.diff_text, (
            "the patch carries bytecode the approver never wrote:\n"
            f"{diff.diff_text}"
        )
        assert "GIT binary patch" not in diff.diff_text, "a binary .pyc was inlined"

    asyncio.run(run())


def test_graph_builder_uses_deterministic_node_ids(tmp_path: Path) -> None:
    task = _task()
    read_plan = ReadPlan(task_id=task.id)
    manifest = WorkspaceManifest(workspace_id="workspace-1")
    builder = ExecutionGraphBuilder()

    first = builder.build(task, read_plan, manifest)
    second = builder.build(task, read_plan, manifest)

    assert [node.id for node in first.nodes] == [node.id for node in second.nodes]
    assert first.nodes[1].id == "task-1:sandbox"


def test_graph_builder_emits_verify_loop_nodes(tmp_path: Path) -> None:
    task = _task()
    read_plan = ReadPlan(task_id=task.id)
    manifest = WorkspaceManifest(workspace_id="workspace-1")

    graph = ExecutionGraphBuilder().build(
        task,
        read_plan,
        manifest,
        verify_loops=2,
        agent_tool_names=("sandbox_read_file", "sandbox_apply_patch"),
    )

    assert [node.id for node in graph.nodes] == [
        "task-1:read",
        "task-1:sandbox",
        "task-1:plan",
        "task-1:agent",
        "task-1:evaluation",
        "task-1:agent:1",
        "task-1:evaluation:1",
        "task-1:approval",
        "task-1:apply",
    ]
    assert graph.nodes[3].dependencies == ("task-1:plan",)
    assert graph.nodes[3].metadata["tool_names"] == [
        "sandbox_read_file",
        "sandbox_apply_patch",
    ]
    assert graph.nodes[3].budget.max_attempts == 2
    assert graph.nodes[3].budget.timeout_seconds == 300.0
    assert graph.nodes[4].budget.max_attempts == 1
    assert graph.nodes[4].budget.timeout_seconds == 600.0
    second_agent = graph.nodes[5]
    assert second_agent.metadata["previous_evaluation_node_id"] == "task-1:evaluation"
    assert graph.nodes[7].dependencies == ("task-1:evaluation:1",)


# -- the read tool describes the root it actually has --------------------------


def test_the_read_tool_describes_a_worktree_as_a_sandbox(tmp_path: Path) -> None:
    """On the task path the root is a worktree, and the wording should say so."""
    from Sprout.execution.file_broker import FileBroker
    from Sprout.execution.sandbox_tool import SandboxReadTool
    from Sprout.security.engine import PolicyEngine
    repo = _git_repo(tmp_path)
    tool = SandboxReadTool(
        SandboxRef(id="s", kind="git_worktree", root=repo),
        FileBroker(PolicyEngine()),
    )

    assert "sandbox" in tool.spec.description
    assert "worktree" in tool.spec.description


def test_the_read_tool_describes_a_plain_directory_as_the_workspace(
    tmp_path: Path,
) -> None:
    """On the conversation path the same class points at the working directory.

    It described itself as reading "inside the sandbox worktree" for both
    paths, so an agent asked to read an ordinary file concluded it had no
    reader and said so — while the tool sat in its list, working. The wording
    was the only thing wrong.
    """
    from Sprout.execution.file_broker import FileBroker
    from Sprout.execution.sandbox_tool import SandboxReadTool
    from Sprout.security.engine import PolicyEngine

    tool = SandboxReadTool(
        SandboxRef(id="cwd", kind="local_directory", root=tmp_path),
        FileBroker(PolicyEngine()),
    )

    description = tool.spec.description
    assert "sandbox" not in description, "a plain directory is not a sandbox"
    assert "worktree" not in description
    assert "source code" in description, "the description should name the use"

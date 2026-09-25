"""Regression tests for the execution-layer audit fixes (R1, R2, R3, R5, R7).

Every behaviour asserted here was missing or wrong before the audit, and none of
it was covered by the suite that was green at the time:

* verification ran in the real workspace while the changes lived in the sandbox;
* ``build_commands`` was carried in node metadata and never read;
* a failing test suite still reached approval and could be applied;
* ``files_changed`` was the literal string ``"workspace"``;
* ``cli_tool_run`` handed the subprocess the whole parent environment and
  ``cli_tool_download`` fetched any URL with no SSRF guard, then ``chmod +x``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from Sprout.context.builder import ContextBuilder
from Sprout.execution.apply import ApplyBroker
from Sprout.execution.change import ChangeProposalBuilder
from Sprout.execution.file_broker import FileBroker
from Sprout.execution.models import (
    ChangeProposalStatus,
    ProcessResult,
)
from Sprout.execution.models import (
    TestResult as CaseResult,
)
from Sprout.orchestration.models import ExecutionNode, NodeType
from Sprout.runtime.changes import ChangeProposalService
from Sprout.runtime.nodes import NodeExecutor
from Sprout.sandbox.git_worktree import GitWorktreeSandbox
from Sprout.security.access import AccessDecision
from Sprout.security.engine import PolicyEngine
from Sprout.security.policy import SecurityPolicy
from Sprout.skills.registry import SkillRegistry
from Sprout.storage.bundle import StorageBundle
from Sprout.storage.local.sqlite.metadata import open_metadata_store
from Sprout.task.models import Task
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.system_tools import CliDownloadTool, CliRunTool
from Sprout.workspace.models import (
    ReadPlan,
    ResourceRef,
    Workspace,
    WorkspaceKind,
    WorkspaceManifest,
)
from Sprout.workspace.read_broker import ReadBroker


class RecordingProcessBroker:
    """ProcessBroker stand-in that records the ``cwd`` of every command."""

    def __init__(self, exit_codes: Mapping[str, int] | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self._exit_codes = dict(exit_codes or {})

    async def run(
        self,
        workspace: Workspace,
        command: Any,
        *,
        cwd: Any = None,
        **kwargs: Any,
    ) -> ProcessResult:
        parts = tuple(str(part) for part in command)
        self.calls.append((parts, Path(cwd)))
        return ProcessResult(
            command=parts,
            exit_code=self._exit_codes.get(parts[0], 0),
            stdout=f"ran {' '.join(parts)}",
            duration_ms=1.0,
            allowed=True,
            allowlisted=True,
        )


class _FlakyProcessBroker:
    """Fails its first command call, then passes subsequent calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self,
        workspace: Workspace,
        command: Any,
        *,
        cwd: Any = None,
        **kwargs: Any,
    ) -> ProcessResult:
        self.calls += 1
        return ProcessResult(
            command=tuple(str(part) for part in command),
            exit_code=1 if self.calls == 1 else 0,
            stdout="transient",
            duration_ms=1.0,
            allowed=True,
            allowlisted=True,
        )


def _storage(tmp_path: Path) -> StorageBundle:
    storage = StorageBundle.in_memory()
    storage.metadata = open_metadata_store(str(tmp_path / "runtime.db"))
    return storage


def _node_executor(storage: StorageBundle, broker: Any) -> NodeExecutor:
    policy = PolicyEngine()
    return NodeExecutor(
        metadata=storage.metadata,
        router=None,
        contexts=ContextBuilder(storage),
        tools=ToolRegistry(),
        skills=SkillRegistry(),
        read_broker=ReadBroker(policy),
        file_broker=FileBroker(policy),
        process_broker=broker,
        apply_broker=ApplyBroker(policy),
    )


def _workspace(root: Path) -> Workspace:
    return Workspace(id="ws", root=root, kind=WorkspaceKind.LOCAL_DIRECTORY)


def _sandbox_node(task_id: str, root: Path) -> ExecutionNode:
    return ExecutionNode(
        id=f"{task_id}:sandbox",
        task_id=task_id,
        type=NodeType.SANDBOX,
        metadata={
            "output": {
                "id": "sandbox-1",
                "kind": "git_worktree",
                "root": str(root),
                "worktree_ref": "sprout-sandbox-test",
            }
        },
    )


def _evaluation_node(task_id: str, **metadata: Any) -> ExecutionNode:
    return ExecutionNode(
        id=f"{task_id}:evaluation",
        task_id=task_id,
        type=NodeType.EVALUATION,
        metadata=metadata,
    )


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


# -- R1 + R3: verification runs where the changes are --------------------------


@pytest.mark.asyncio
async def test_evaluation_runs_test_and_build_commands_in_the_sandbox(tmp_path) -> None:
    storage = _storage(tmp_path)
    task = Task(id="task-eval", workspace_id="ws")
    sandbox_root = tmp_path / ".sprout-eval"
    sandbox_root.mkdir()
    await storage.metadata.save_execution_node(_sandbox_node(task.id, sandbox_root))

    broker = RecordingProcessBroker()
    executor = _node_executor(storage, broker)
    node = _evaluation_node(
        task.id,
        test_commands=["pytest -q"],
        build_commands=["python -m build"],
    )

    output = await executor._evaluation(node, _workspace(tmp_path), task)

    assert [parts for parts, _ in broker.calls] == [
        ("pytest", "-q"),
        ("python", "-m", "build"),
    ]
    # R1: both commands run inside the sandbox worktree, not the real workspace.
    assert [cwd for _, cwd in broker.calls] == [sandbox_root, sandbox_root]
    assert output["cwd"] == str(sandbox_root)
    # R3: build commands are executed, not just carried in node metadata.
    assert output["build_commands"] == ["python -m build"]
    assert output["status"] == "passed"
    assert [item["name"] for item in output["test_results"]] == [
        "test: pytest -q",
        "build: python -m build",
    ]
    storage.metadata.close()


@pytest.mark.asyncio
async def test_evaluation_without_a_sandbox_falls_back_to_the_workspace(tmp_path) -> None:
    storage = _storage(tmp_path)
    task = Task(id="task-nosandbox", workspace_id="ws")
    broker = RecordingProcessBroker()
    executor = _node_executor(storage, broker)

    output = await executor._evaluation(
        _evaluation_node(task.id, test_commands=["pytest -q"]),
        _workspace(tmp_path),
        task,
    )

    assert [cwd for _, cwd in broker.calls] == [tmp_path]
    assert output["sandbox_root"] is None
    storage.metadata.close()


@pytest.mark.asyncio
async def test_evaluation_reports_a_failing_command(tmp_path) -> None:
    storage = _storage(tmp_path)
    task = Task(id="task-fail", workspace_id="ws")
    broker = RecordingProcessBroker({"pytest": 1})
    executor = _node_executor(storage, broker)

    output = await executor._evaluation(
        _evaluation_node(task.id, test_commands=["pytest -q"]),
        _workspace(tmp_path),
        task,
    )

    assert output["status"] == "failed"
    assert output["failed_commands"] == ["test: pytest -q"]
    assert output["test_results"][0]["passed"] is False
    storage.metadata.close()


@pytest.mark.asyncio
async def test_evaluation_falls_back_to_python_compileall(tmp_path) -> None:
    storage = _storage(tmp_path)
    task = Task(id="task-fallback", workspace_id="ws")
    sandbox_root = tmp_path / ".sprout-fallback"
    sandbox_root.mkdir()
    await storage.metadata.save_execution_node(_sandbox_node(task.id, sandbox_root))
    workspace = Workspace(
        id="ws",
        root=tmp_path,
        kind=WorkspaceKind.LOCAL_DIRECTORY,
        manifest=WorkspaceManifest(
            workspace_id="ws",
            detected_languages=("python",),
        ),
    )
    broker = RecordingProcessBroker()
    executor = _node_executor(storage, broker)

    output = await executor._evaluation(
        _evaluation_node(task.id),
        workspace,
        task,
    )

    assert output["check_commands"] == ["python -m compileall -q ."]
    assert output["status"] == "passed"
    assert [parts for parts, _ in broker.calls] == [
        ("python", "-m", "compileall", "-q", ".")
    ]
    storage.metadata.close()


@pytest.mark.asyncio
async def test_evaluation_retries_a_transient_command_failure(tmp_path) -> None:
    storage = _storage(tmp_path)
    task = Task(id="task-retry", workspace_id="ws")
    sandbox_root = tmp_path / ".sprout-retry"
    sandbox_root.mkdir()
    await storage.metadata.save_execution_node(_sandbox_node(task.id, sandbox_root))
    broker = _FlakyProcessBroker()
    executor = _node_executor(storage, broker)

    output = await executor._evaluation(
        _evaluation_node(
            task.id,
            test_commands=["pytest -q"],
            verification_attempts=2,
        ),
        _workspace(tmp_path),
        task,
    )

    assert broker.calls == 2
    assert output["status"] == "passed"
    assert output["results"][0]["attempts"] == 2
    storage.metadata.close()


@pytest.mark.asyncio
async def test_evaluation_runs_static_checks_on_changed_files(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "init")

    workspace = Workspace(
        id="ws",
        root=repo,
        kind=WorkspaceKind.GIT_REPOSITORY,
        manifest=WorkspaceManifest(
            workspace_id="ws",
            detected_languages=("python",),
        ),
    )
    sandbox = GitWorktreeSandbox(workspace)
    ref = await sandbox.create(branch="sprout-sandbox-static")
    try:
        (ref.root / "app.py").write_text(
            "def main():\n    return 2\n", encoding="utf-8"
        )
        storage = _storage(tmp_path)
        task = Task(id="task-static", workspace_id="ws")
        await storage.metadata.save_execution_node(_sandbox_node(task.id, ref.root))

        monkeypatch.setattr(
            "Sprout.runtime.nodes.shutil.which",
            lambda name: "/usr/bin/ruff" if name == "ruff" else None,
        )
        executor = _node_executor(storage, RecordingProcessBroker())
        output = await executor._evaluation(
            _evaluation_node(task.id),
            workspace,
            task,
        )

        assert output["status"] == "passed"
        assert "python -m compileall -q app.py" in output["check_commands"]
        assert "ruff check app.py" in output["check_commands"]
        storage.metadata.close()
    finally:
        await sandbox.remove(ref)


def test_agent_prompt_includes_plan_and_feedback() -> None:
    prompt = NodeExecutor._agent_prompt(
        Task(id="task-1", instruction="fix the bug"),
        Workspace(id="ws", root=Path("."), kind=WorkspaceKind.LOCAL_DIRECTORY),
        (),
        feedback={"status": "failed", "failed_commands": ["test: pytest -q"]},
        plan="1. edit a.py\n2. add a test",
    )

    assert "Plan from the planning step:" in prompt
    assert "1. edit a.py" in prompt
    assert "Previous verification feedback:" in prompt
    assert "test: pytest -q" in prompt


# -- R5 + R7: the proposal carries the verification and the file names ---------


@pytest.mark.asyncio
async def test_approval_carries_the_failed_verification_and_raises_the_risk(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "init")

    workspace = Workspace(id="ws", root=repo, kind=WorkspaceKind.GIT_REPOSITORY)
    sandbox = GitWorktreeSandbox(workspace)
    ref = await sandbox.create(branch="sprout-sandbox-failed")
    try:
        (ref.root / "tracked.txt").write_text("two", encoding="utf-8")

        storage = _storage(tmp_path)
        task = Task(id="task-approval", workspace_id="ws")
        await storage.metadata.save_execution_node(_sandbox_node(task.id, ref.root))
        await storage.metadata.save_execution_node(
            ExecutionNode(
                id=f"{task.id}:evaluation",
                task_id=task.id,
                type=NodeType.EVALUATION,
                metadata={
                    "output": {
                        "status": "failed",
                        "failed_commands": ["test: pytest -q"],
                        "test_results": [
                            {
                                "name": "test: pytest -q",
                                "passed": False,
                                "output": "1 failed",
                                "duration_ms": 3.0,
                            }
                        ],
                    }
                },
            )
        )

        executor = _node_executor(storage, RecordingProcessBroker())
        output = await executor._approval(workspace, task)

        proposals = await storage.metadata.list_change_proposals(task.id)
        assert len(proposals) == 1
        proposal = proposals[0]
        # R5: the failure travels onto the proposal instead of being dropped.
        assert [item.name for item in proposal.test_results] == ["test: pytest -q"]
        assert proposal.test_results[0].passed is False
        assert proposal.risk == "high"
        assert output["waiting"] is True
        assert output["test_status"] == "failed"
        assert output["failed_commands"] == ["test: pytest -q"]
        assert set(proposal.files_changed) == {"tracked.txt"}
        storage.metadata.close()
    finally:
        await sandbox.remove(ref)


@pytest.mark.asyncio
async def test_approval_skips_proposal_when_no_files_changed(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "init")

    workspace = Workspace(id="ws", root=repo, kind=WorkspaceKind.GIT_REPOSITORY)
    sandbox = GitWorktreeSandbox(workspace)
    ref = await sandbox.create(branch="sprout-sandbox-clean")
    try:
        storage = _storage(tmp_path)
        task = Task(id="task-clean", workspace_id="ws")
        await storage.metadata.save_execution_node(_sandbox_node(task.id, ref.root))

        executor = _node_executor(storage, RecordingProcessBroker())
        output = await executor._approval(workspace, task)

        assert output.get("waiting") is None
        assert output["status"] == "no_changes"
        assert await storage.metadata.list_change_proposals(task.id) == []
        storage.metadata.close()
    finally:
        await sandbox.remove(ref)


@pytest.mark.asyncio
async def test_approval_lists_the_real_changed_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "init")

    workspace = Workspace(id="ws", root=repo, kind=WorkspaceKind.GIT_REPOSITORY)
    sandbox = GitWorktreeSandbox(workspace)
    ref = await sandbox.create(branch="sprout-sandbox-changed")
    try:
        (ref.root / "tracked.txt").write_text("two", encoding="utf-8")
        (ref.root / "brand_new.py").write_text("print('hi')\n", encoding="utf-8")

        changed = await sandbox.changed_files(ref)
        # R7: the new file is untracked, so ``git diff --name-only`` would miss
        # it; the status view is what actually covers the change set.
        assert set(changed) == {"tracked.txt", "brand_new.py"}

        storage = _storage(tmp_path)
        task = Task(id="task-files", workspace_id="ws")
        await storage.metadata.save_execution_node(_sandbox_node(task.id, ref.root))
        executor = _node_executor(storage, RecordingProcessBroker())
        output = await executor._approval(workspace, task)

        proposals = await storage.metadata.list_change_proposals(task.id)
        assert set(proposals[0].files_changed) == {"tracked.txt", "brand_new.py"}
        assert output["files_changed"] and "workspace" not in output["files_changed"]
        storage.metadata.close()
    finally:
        await sandbox.remove(ref)


# -- R5: failing verification is a gate, not a footnote -----------------------


def _approved_proposal(task_id: str, *test_results: CaseResult):
    return replace(
        ChangeProposalBuilder().build(
            task_id=task_id, test_results=tuple(test_results)
        ),
        status=ChangeProposalStatus.APPROVED,
    )


@pytest.mark.asyncio
async def test_apply_refuses_a_proposal_whose_verification_failed(tmp_path) -> None:
    storage = _storage(tmp_path)
    await storage.metadata.save_workspace(_workspace(tmp_path))
    await storage.metadata.save_task(Task(id="task-apply", workspace_id="ws"))
    proposal = _approved_proposal(
        "task-apply", CaseResult(name="test: pytest -q", passed=False, output="1 failed")
    )
    await storage.metadata.save_change_proposal(proposal)

    service = ChangeProposalService(
        storage.metadata, storage.operational, ApplyBroker(PolicyEngine())
    )

    blocked = await service.apply(proposal.id)
    assert blocked.applied is False
    assert "test: pytest -q" in blocked.reason
    assert "Verification failed" in blocked.reason

    # The override exists, but it has to be asked for explicitly.
    overridden = await service.apply(proposal.id, allow_failing_tests=True)
    assert "Verification failed" not in overridden.reason
    storage.metadata.close()


@pytest.mark.asyncio
async def test_apply_is_not_blocked_by_passing_verification(tmp_path) -> None:
    storage = _storage(tmp_path)
    await storage.metadata.save_workspace(_workspace(tmp_path))
    await storage.metadata.save_task(Task(id="task-ok", workspace_id="ws"))
    proposal = _approved_proposal(
        "task-ok", CaseResult(name="test: pytest -q", passed=True)
    )
    await storage.metadata.save_change_proposal(proposal)

    service = ChangeProposalService(
        storage.metadata, storage.operational, ApplyBroker(PolicyEngine())
    )
    result = await service.apply(proposal.id)

    assert "Verification failed" not in result.reason
    storage.metadata.close()


# -- R2: the tool path stops being a hole in the process policy ---------------


@pytest.mark.asyncio
async def test_cli_run_tool_does_not_inherit_the_parent_environment(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SPROUT_TEST_LEAKED_SECRET", "super-secret-value")
    tool = CliRunTool(allowed_roots=(tmp_path,))

    result = await tool.invoke(
        {
            "command": sys.executable,
            "args": [
                "-c",
                "import os; print(os.environ.get('SPROUT_TEST_LEAKED_SECRET', '<absent>'))",
            ],
            "cwd": str(tmp_path),
            "timeout": 120,
        }
    )

    assert result.ok, result.error
    assert "super-secret-value" not in result.content
    assert "<absent>" in result.content


@pytest.mark.asyncio
async def test_cli_run_tool_keeps_asking_for_explicit_env(tmp_path) -> None:
    tool = CliRunTool(allowed_roots=(tmp_path,))

    result = await tool.invoke(
        {
            "command": sys.executable,
            "args": ["-c", "import os; print(os.environ.get('SPROUT_TEST_EXPLICIT', ''))"],
            "cwd": str(tmp_path),
            "env": {"SPROUT_TEST_EXPLICIT": "declared"},
            "timeout": 120,
        }
    )

    assert result.ok, result.error
    assert "declared" in result.content


@pytest.mark.asyncio
async def test_cli_run_tool_denies_a_cwd_outside_the_allowed_roots(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = CliRunTool(allowed_roots=(allowed,))

    result = await tool.invoke(
        {
            "command": sys.executable,
            "args": ["-c", "print('should not run')"],
            "cwd": str(outside),
        }
    )

    assert result.ok is False
    assert "outside the allowed roots" in result.error


@pytest.mark.asyncio
async def test_cli_download_tool_blocks_the_metadata_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    tool = CliDownloadTool()

    result = await tool.invoke({"url": "http://169.254.169.254/latest/meta-data/"})

    assert result.ok is False
    assert "blocked" in result.error.lower()
    assert "169.254.169.254" in result.error


def test_cli_download_tool_is_high_risk_under_the_default_policy() -> None:
    assert CliDownloadTool.spec.risk_level == "high"
    decision = SecurityPolicy().evaluate(
        tool="cli_tool_download", risk_level=CliDownloadTool.spec.risk_level
    )
    assert decision.decision is AccessDecision.REQUIRE_APPROVAL


def test_cli_run_tool_is_high_risk_under_the_default_policy() -> None:
    decision = SecurityPolicy().evaluate(
        tool="cli_tool_run", risk_level=CliRunTool.spec.risk_level
    )
    assert decision.decision is AccessDecision.REQUIRE_APPROVAL


# -- workspace escape guard, verified through a real reparse point -------------


@pytest.mark.asyncio
async def test_read_broker_rejects_a_junction_escape(tmp_path) -> None:
    """A directory junction exercises the same escape guard as a symlink.

    ``test_authz.py`` asserts this with a symlink, but that test skips wherever
    symlink creation is unavailable or silently neutered. A junction needs no
    privilege, so it keeps the guard under test on such hosts: a path that
    resolves through the junction to a directory outside the workspace has to be
    refused before anything is read.
    """
    if os.name != "nt":
        pytest.skip("Windows junction escape guard requires a Windows shell")

    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified", encoding="utf-8")

    junction = workspace_dir / "junc"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if created.returncode != 0 or not junction.exists():  # pragma: no cover
        pytest.skip("junctions are unavailable in this environment")

    workspace = Workspace(id="ws-gate", root=workspace_dir, kind=WorkspaceKind.LOCAL_DIRECTORY)
    try:
        assert ReadBroker._safe_target(workspace, "junc") is None
        assert ReadBroker._safe_target(workspace, "junc/secret.txt") is None

        plan = ReadPlan(
            task_id="task-1",
            resources=(ResourceRef(workspace_id="ws-gate", path="junc/secret.txt"),),
        )
        results = await ReadBroker(PolicyEngine()).read(workspace, plan)

        assert results[0].decision is AccessDecision.DENY
        assert results[0].error == "Path escapes workspace boundary"
        assert results[0].content == ""
    finally:
        # os.rmdir removes the junction itself and leaves the target intact.
        try:
            os.rmdir(str(junction))
        except OSError:  # pragma: no cover
            pass

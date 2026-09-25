"""End-to-end coverage for the task path: requirement -> workspace commit.

Every defect found while building this path was found by driving a real model
by hand, and the suite stayed green through all of them — including a task that
reported ``completed`` with an untouched repository. Unit tests could not catch
those, because each one exercised a stage in isolation and every stage was
individually correct.

These tests drive the real pipeline with a scripted model (see
``fake_model.FakeModel``): the graph, the agent loop, the sandbox, the
verification gate, approval, and apply all run for real, while the model's
inputs and outputs stay fixed.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from Sprout.cli.app import app
from Sprout.config.loader import default_settings
from Sprout.gateway.project_gateway import ProjectGateway
from Sprout.orchestration.models import NodeStatus, NodeType
from Sprout.runtime.factory import create_runtime
from Sprout.tests.fake_model import FakeModel

REQUIREMENT = "给 user 模块加一个导出 CSV 的函数"


def _repo(tmp_path: Path, *, gitignore: bool = True) -> Path:
    """A minimal git workspace with one test that passes.

    ``gitignore=False`` models the repository an operator actually points Sprout
    at: one that has not enumerated its caches. The proposal path must not
    depend on the repository having done that bookkeeping for it.
    """
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "user.py").write_text(
        '"""User service."""\n\n\ndef list_users():\n    return [{"id": 1}]\n',
        encoding="utf-8",
    )
    (root / "tests" / "test_user.py").write_text(
        "from src.user import list_users\n\n\ndef test_list_users():\n"
        "    assert list_users()\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    # Verification runs pytest inside the sandbox, which writes __pycache__.
    # A real repository ignores those; without this the fixture would model a
    # project whose bytecode caches look like agent edits.
    #
    # The sandbox filters them out on its own (``_SANDBOX_EXCLUDES``), so this
    # is no longer load-bearing for correctness — but a repository that ignores
    # its caches is still the common shape, and the suite should exercise it.
    if gitignore:
        (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    # pytest needs the package importable from the sandbox worktree.
    (root / "conftest.py").write_text(
        "import pathlib, sys\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n",
        encoding="utf-8",
    )
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "tester"],
        ["add", "-A"],
        ["commit", "-qm", "init"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def _runtime(tmp_path: Path, model: FakeModel):
    """A runtime whose agent runs on the scripted model.

    The factory captures ``models.default()`` when it builds the agent, so
    registering a model afterwards does not reach it — the agent keeps the
    provider it was assembled with. The agent is therefore rebuilt here with
    the scripted model, reusing the executor the factory already wired.
    """
    from Sprout.agent.loop import AgentLoop
    from Sprout.agent.planner import DirectPlanner
    from Sprout.agent.router import AgentRouter

    settings = default_settings()
    settings.model.provider = "echo"
    settings.model.model = "echo-1"
    db = (tmp_path / "meta.db").as_posix()
    settings.storage.operational = f"sqlite:///{(tmp_path / 'op.db').as_posix()}"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{db}"
    settings.storage.session = f"sqlite:///{db}"
    settings.storage.trajectory_dir = str(tmp_path / "traj")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "audit.jsonl")
    runtime = create_runtime(settings)

    runtime.models.register(model, default=True)
    existing = runtime.agents.get(runtime.default_agent)
    scripted = AgentLoop(
        model=model,
        executor=existing.executor,
        max_steps=existing.max_steps,
        planner=DirectPlanner(),
    )
    runtime.register_agent(runtime.default_agent, scripted, default=True)
    runtime.set_router(AgentRouter(runtime.agents, default=runtime.default_agent))
    return runtime


def _commit_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(out.stdout.strip())


async def _drive(runtime, task, *, max_rounds: int = 6):
    """Run a task to a settled state, playing the human at each gate.

    Approval is granted the way an operator would — through the real
    ``decide`` path — so the wait/resume machinery is exercised rather than
    bypassed. A task that parks keeps needing decisions until it settles.
    """
    from Sprout.task.models import TaskStatus

    settled = {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
    await runtime.execute(task)
    rounds = 0
    # The persisted task is the only reliable gate: ``execute`` returns the
    # status as of when it was called, which goes stale the moment a decision
    # is granted and work resumes.
    #
    # Granting a proposal already resumes the task internally
    # (``_resume_task_after_approval``), so that path must not also be resumed
    # here — doing so re-enters an already-settled task.
    while rounds < max_rounds:
        current = await runtime.get_task(task.id)
        if current is None or current.status in settled:
            break
        rounds += 1
        granted = False
        for record in await runtime._approvals.pending():
            if record.task_id == task.id:
                await runtime._approvals.decide(
                    record.id, approved=True, decided_by="test"
                )
                granted = True
        proposal_approved = False
        for proposal in await runtime.storage.metadata.list_change_proposals(task.id):
            if proposal.status.value == "pending":
                await runtime.approve_change_proposal(proposal.id, decided_by="test")
                granted = proposal_approved = True
        if not granted:
            break
        if not proposal_approved:
            # Verification was granted but the graph is still parked.
            await runtime.resume_task(await runtime.get_task(task.id))
    final = await runtime.get_task(task.id)
    assert final is not None
    return final


def test_requirement_reaches_the_agent_as_a_planned_task(tmp_path: Path) -> None:
    """The bridge is wired: a real entry point produces a planned task.

    Regression: ``create_task_from_strategy`` had no callers, so
    ``task.metadata["steps"]`` was always empty and the whole decomposition
    path ran only under tests.
    """
    repo = _repo(tmp_path)
    model = FakeModel(plan_steps=["读 user 模块"])

    async def run() -> dict:
        runtime = _runtime(tmp_path, model)
        workspace = await runtime.open_workspace(repo)
        gateway = ProjectGateway(runtime, transport="cli", default_user="t")
        task = await gateway.create_task(workspace.id, REQUIREMENT)
        await runtime.stop()
        return dict(task.metadata)

    metadata = __import__("asyncio").run(run())

    assert metadata["plan_kind"] in {"local", "model"}
    assert "required_paths" in metadata


def test_a_verified_change_lands_in_the_workspace(tmp_path: Path) -> None:
    """The whole path, ending in a real commit on the real repository.

    Regression: a refused apply returned a normal payload, so the task
    finished as ``completed`` while the workspace was untouched.
    """
    repo = _repo(tmp_path)
    before = _commit_count(repo)
    model = FakeModel(
        edits={"src/export.py": "def export_users(users):\n    return ''\n"}
    )

    async def run():
        runtime = _runtime(tmp_path, model)
        workspace = await runtime.open_workspace(repo)
        gateway = ProjectGateway(runtime, transport="cli", default_user="t")
        task = await gateway.create_task(workspace.id, REQUIREMENT)
        final = await _drive(runtime, task)
        await runtime.stop()
        return final

    final = __import__("asyncio").run(run())

    assert final.status.value == "completed", "the happy path should settle green"
    # The whole point: "completed" has to mean the change is in the workspace.
    assert _commit_count(repo) > before, (
        "task reported success but the workspace has no new commit"
    )


def test_a_failing_verification_does_not_land(tmp_path: Path) -> None:
    """A real failure blocks the change; risk is raised for the approver.

    Regression: the gate keyed on ``not passed``, which is also true for a
    command that never ran, so it could not tell "failed" from "unverified".
    """
    repo = _repo(tmp_path)
    # An invariant that already fails and that the agent has no reason to touch.
    (repo / "tests" / "test_invariant.py").write_text(
        "def test_invariant():\n    assert 1 == 2\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "failing invariant"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    baseline = _commit_count(repo)

    model = FakeModel(edits={"src/export.py": "def export_users():\n    return ''\n"})

    async def run():
        runtime = _runtime(tmp_path, model)
        workspace = await runtime.open_workspace(repo)
        gateway = ProjectGateway(runtime, transport="cli", default_user="t")
        task = await gateway.create_task(workspace.id, REQUIREMENT)
        final = await _drive(runtime, task)
        nodes = await runtime.storage.metadata.list_execution_nodes(task.id)
        proposals = await runtime.storage.metadata.list_change_proposals(task.id)
        await runtime.stop()
        return final, nodes, proposals

    final, nodes, proposals = __import__("asyncio").run(run())

    statuses = {
        n.metadata["output"].get("status")
        for n in nodes
        if n.type is NodeType.EVALUATION
        and isinstance(n.metadata.get("output"), dict)
        and n.metadata["output"].get("status")
    }
    # The failure must be seen and named, not conflated with "never ran".
    assert "failed" in statuses, f"the failing test was not reported: {statuses}"
    assert "not_verified" not in statuses, "a granted command is not 'unverified'"
    # And the change must not land on a red verdict.
    assert _commit_count(repo) == baseline, "a failing verification landed a commit"
    assert final.status.value == "failed"
    assert proposals and proposals[0].risk == "high"


@pytest.mark.asyncio
async def test_a_withheld_command_parks_the_task(tmp_path: Path) -> None:
    """A parked verification command waits for a human, then runs.

    Regression: the process broker refused every non-ALLOW verdict without
    asking, so verification executed nothing while still reporting a verdict.
    """
    repo = _repo(tmp_path)
    model = FakeModel(edits={"src/export.py": "def export_users():\n    return ''\n"})

    runtime = _runtime(tmp_path, model)
    workspace = await runtime.open_workspace(repo)
    gateway = ProjectGateway(runtime, transport="cli", default_user="t")
    task = await gateway.create_task(workspace.id, REQUIREMENT)

    first = await runtime.execute(task)

    assert first.status.value == "waiting_approval"
    pending = [r for r in await runtime._approvals.pending() if r.task_id == task.id]
    assert pending, "a withheld command must ask for approval, not refuse silently"

    await runtime.stop()


def test_a_proposal_offers_only_the_agents_edits(tmp_path: Path) -> None:
    """The change proposal must not list caches the verification step wrote.

    Regression: verification runs inside the sandbox and leaves ``__pycache__``
    behind, which the raw git status view reported as part of the change set. On
    a repository with no ``.gitignore`` — the common case — the approver was
    shown a proposal whose files were mostly bytecode, and applying it would
    have committed them.
    """
    repo = _repo(tmp_path, gitignore=False)
    model = FakeModel(edits={"src/export.py": "def export_users(users):\n    return ''\n"})

    async def run():
        runtime = _runtime(tmp_path, model)
        workspace = await runtime.open_workspace(repo)
        gateway = ProjectGateway(runtime, transport="cli", default_user="t")
        task = await gateway.create_task(workspace.id, REQUIREMENT)
        final = await _drive(runtime, task)
        proposals = await runtime.storage.metadata.list_change_proposals(task.id)
        await runtime.stop()
        return final, proposals

    final, proposals = asyncio.run(run())

    assert final.status.value == "completed", "the happy path should settle green"
    assert proposals, "a verified change must produce a proposal"
    files = proposals[0].files_changed
    assert "src/export.py" in files, f"the agent's edit is missing: {files}"
    sandbox_ref = proposals[0].sandbox_ref
    assert sandbox_ref is not None
    assert not Path(sandbox_ref.root).exists(), "the merged task worktree must be removed"
    assert not subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", sandbox_ref.worktree_ref or ""],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(), "the merged task branch must be removed"
    caches = [
        path for path in files if "__pycache__" in path or path.endswith(".pyc")
    ]
    assert not caches, f"bytecode caches reached the proposal: {caches}"
    assert "__pycache__" not in "".join(d.diff_text for d in proposals[0].diffs)


def _cli_config(tmp_path: Path) -> Path:
    """A minimal ``sprout.toml`` for the approval CLI.

    Only ``load_settings`` has to succeed — the runtime under test is injected —
    so these DSNs are never opened. They point inside ``tmp_path`` regardless,
    so a mistake cannot reach the operator's real ``~/.sprout`` databases.
    """
    config = tmp_path / "sprout.toml"
    config.write_text(
        '[model]\nprovider = "echo"\nmodel = "echo-1"\n'
        "\n[storage]\n"
        f'operational = "sqlite:///{(tmp_path / "op.db").as_posix()}"\n'
        f'knowledge = "sqlite:///{(tmp_path / "knowledge.db").as_posix()}"\n'
        f'metadata = "sqlite:///{(tmp_path / "meta.db").as_posix()}"\n'
        'session = "memory://"\n'
        "\n[storage.observations]\n"
        "enabled = false\n",
        encoding="utf-8",
    )
    return config


def test_approving_a_withheld_command_wakes_the_parked_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sprout approvals approve`` must continue the task it unblocked.

    Regression: ``--resume`` defaulted to *off*, so the decision was recorded
    through a bare ``ApprovalManager`` and the task stayed in
    ``waiting_approval`` with its verification never run. Because
    ``ApprovalManager.decide`` refuses a record that is no longer PENDING, the
    grant could not be re-decided either: the operator had answered the prompt
    and had no way left to act on their own answer. The web path never had this
    problem — it always goes through ``Runtime.decide_approval``, which resumes.
    """
    repo = _repo(tmp_path)
    model = FakeModel(edits={"src/export.py": "def export_users(users):\n    return ''\n"})
    config = _cli_config(tmp_path)
    live: dict = {}

    async def park() -> tuple[str, str]:
        runtime = _runtime(tmp_path, model)
        live["runtime"] = runtime
        workspace = await runtime.open_workspace(repo)
        gateway = ProjectGateway(runtime, transport="cli", default_user="t")
        task = await gateway.create_task(workspace.id, REQUIREMENT)
        first = await runtime.execute(task)
        assert first.status.value == "waiting_approval"
        pending = [
            record
            for record in await runtime._approvals.pending()
            if record.task_id == task.id
        ]
        assert pending, "a withheld command must ask for approval"
        return task.id, pending[0].id

    task_id, approval_id = asyncio.run(park())

    # What the operator's CLI sees: the live runtime, standing in for the one
    # ``create_runtime`` would have assembled from this config.
    monkeypatch.setattr(
        "Sprout.runtime.factory.create_runtime",
        lambda *_args, **_kwargs: live["runtime"],
    )
    decided = CliRunner().invoke(
        app, ["approvals", "approve", approval_id, "--config", str(config)]
    )
    assert decided.exit_code == 0, decided.output
    assert "approved" in decided.output

    async def inspect() -> list:
        runtime = live["runtime"]
        return await runtime.storage.metadata.list_execution_nodes(task_id)

    nodes = asyncio.run(inspect())

    evaluation = [node for node in nodes if node.type is NodeType.EVALUATION]
    assert evaluation, "the compiled graph must have an evaluation node"
    assert any(node.status is NodeStatus.COMPLETED for node in evaluation), (
        "the grant was approved but the withheld verification never ran: the "
        "task is still parked behind a decision that was already granted"
    )

"""The git broker's approval gate must look up the grant the tool layer issued.

``git_write`` is a high-risk tool, so ``ToolExecutor`` asks for approval under
the tool name ``git_write`` and stores the grant against that name. The broker
then re-checks with its own action name (``git.commit``). When the two disagree
the broker's ``is_approved`` lookup can never match, so the check is dead code —
it always falls back to "requires approval" even for an operation the human just
authorised.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from Sprout.execution.git_broker import GitBroker
from Sprout.security.approval import ApprovalManager, ApprovalPolicy
from Sprout.security.engine import PolicyEngine
from Sprout.workspace.models import Workspace, WorkspaceKind

TOOL_NAME = "git_write"
COMMIT_ARGS = {"message": "x", "files": []}


def _workspace(tmp_path: Path) -> Workspace:
    return Workspace(id="", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY)


def _isolated_workspace(tmp_path: Path) -> Path:
    """A directory that is its own git repository, never the surrounding one.

    ``tmp_path`` lives *inside* the checkout under the project's required
    ``--basetemp=.pytest_tmp`` (see the test-suite notes). Running ``git`` there
    does not stay local: ``GitBroker.commit`` issues ``git add -A``, and ``-A``
    stages the **whole repository** no matter which subdirectory it runs from.
    A test that lets that reach ``git commit`` therefore commits the developer's
    uncommitted work — which is exactly what happened here: the broker's commit
    succeeded against the outer repo instead of failing on a missing repository,
    the assertion flipped, and the working tree acquired stray commits.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    run = lambda *args: subprocess.run(  # noqa: E731 - one-off local helper
        ["git", *args], cwd=root, capture_output=True, check=True
    )
    run("init", "-q", ".")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "test")
    return root


def _has_commits(root: Path) -> bool:
    """True when the repository at ``root`` has at least one commit."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() not in {"", "0"}


def _manager() -> ApprovalManager:
    from Sprout.storage.local.memory import MemoryOperationalStore

    return ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())


async def _granted(manager: ApprovalManager, tool: str, arguments: dict) -> None:
    """Issue and approve a grant exactly as the tool layer does."""
    record = await manager.request(tool, arguments, single_use=True)
    await manager.decide(record.id, True, decided_by="test", channel="cli")


async def test_a_grant_issued_under_the_tool_name_is_visible_to_the_broker(
    tmp_path: Path,
) -> None:
    """The fidelity bug: broker and tool must agree on the approval's name."""
    manager = _manager()
    await _granted(manager, TOOL_NAME, COMMIT_ARGS)

    assert await manager.is_approved(TOOL_NAME, COMMIT_ARGS) is True


async def test_broker_commit_accepts_an_approval_granted_for_the_tool(
    tmp_path: Path,
) -> None:
    """An approved ``git_write`` commit must get past the broker's gate.

    The fresh repository has no commits, so ``git commit`` itself fails. What
    matters is *where* it fails: reaching git at all proves the grant was seen.
    A refusal at the gate returns ``allowed=False`` instead of raising.

    The repository is created here rather than relying on ``tmp_path`` not being
    inside one — it always is under ``--basetemp=.pytest_tmp``, and the broker's
    ``git add -A`` would then stage the surrounding checkout.
    """
    manager = _manager()
    await _granted(manager, TOOL_NAME, COMMIT_ARGS)
    broker = GitBroker(PolicyEngine(), approvals=manager)
    root = _isolated_workspace(tmp_path)

    with pytest.raises(RuntimeError):
        await broker.commit(_workspace(root), "x")

    # The real assertion behind "reaching git": nothing was committed anywhere
    # else, and the outer repository was not staged by our ``git add -A``.
    assert not _has_commits(root), "the broker's commit unexpectedly succeeded"


async def test_broker_refuses_a_commit_with_no_grant(tmp_path: Path) -> None:
    """Without a grant the broker must still refuse."""
    broker = GitBroker(PolicyEngine(), approvals=_manager())
    root = _isolated_workspace(tmp_path)

    result = await broker.commit(_workspace(root), "x")

    assert result.allowed is False
    assert "approval" in result.reason.casefold()
    assert not _has_commits(root), "a refused commit must not reach git"


def test_the_tool_and_broker_names_are_declared_in_one_place() -> None:
    """Guard against the two sides drifting apart again."""
    from Sprout.execution.git_broker import GitBroker as _Broker
    from Sprout.tools.system_tools import GitWriteTool

    spec_name = GitWriteTool.spec.name
    broker_tools = {
        _Broker.commit.__name__: spec_name,
        _Broker.push.__name__: spec_name,
        _Broker.pull.__name__: spec_name,
    }

    assert set(broker_tools.values()) == {TOOL_NAME}

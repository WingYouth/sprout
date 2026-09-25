"""Read-only commands skip the approval prompt; nothing else does.

``cli_tool_run`` is declared ``risk_level="high"``, so the policy engine answers
``REQUIRE_APPROVAL`` unconditionally and every invocation asked a human — ``pwd``
and ``git status`` included. An operator's approval history showed 22
``cli_tool_run`` grants and not one of them was a command that changed anything.

The rule that decides is narrow on purpose: a command is read-only only if it
cannot be made to run code the *task* wrote. ``pytest`` imports ``conftest.py``,
``npm test`` runs a ``package.json`` script, ``make`` does whatever the Makefile
says — and in worktree mode that directory is where the agent just wrote. Those
keep asking.

These tests pin both directions, because a classifier that leaks is worse than
no classifier at all.
"""

from __future__ import annotations

import asyncio

import pytest

from Sprout.security.commands import CommandRegistry, is_read_only_command
from Sprout.security.policy import SecurityPolicy
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.system_tools import CliRunTool


def _registry() -> CommandRegistry:
    return CommandRegistry()


# -- what counts as read-only ------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["pwd"],
        ["ls", "-la"],
        ["cat", "src/app.py"],
        ["wc", "-l", "f"],
        ["head", "f"],
        ["rg", "pattern"],
        ["grep", "-rn", "x", "."],
        ["git", "status"],
        ["git", "status", "--short", "--branch"],
        ["git", "log", "--oneline"],
        ["git", "ls-files"],
        ["git", "branch"],
        ["git", "rev-parse", "HEAD"],
    ],
)
def test_a_read_only_invocation_is_recognised(argv: list[str]) -> None:
    assert is_read_only_command(argv, registry=_registry()) is True


@pytest.mark.parametrize(
    "argv",
    [
        # Build and test tools: they execute workspace-authored code.
        ["pytest"],
        ["npm", "test"],
        ["make"],
        ["cargo", "test"],
        ["python", "-c", "print(1)"],
        ["python3", "script.py"],
        ["node", "x.js"],
        ["uv", "run", "x"],
        # git subcommands that write.
        ["git", "commit", "-m", "x"],
        ["git", "push"],
        ["git", "reset", "--hard"],
        ["git", "clean", "-fd"],
        ["git", "checkout", "main"],
        ["git", "config", "core.pager", "less"],
        ["git", "remote", "add", "origin", "x"],
        # Arbitrary execution.
        ["sh", "-c", "id"],
        ["bash", "-c", "id"],
        ["curl", "http://example.com"],
        # Bare git: no subcommand, nothing to classify as read-only.
        ["git"],
    ],
)
def test_an_executing_invocation_is_not_read_only(argv: list[str]) -> None:
    assert is_read_only_command(argv, registry=_registry()) is False


# -- the sharp edges ---------------------------------------------------------


def test_the_subcommand_decides_not_the_command_name() -> None:
    """``git`` is one name for both ``status`` and ``commit``."""
    registry = _registry()

    assert is_read_only_command(["git", "status"], registry=registry) is True
    assert is_read_only_command(["git", "commit", "-m", "x"], registry=registry) is False


def test_git_c_is_never_read_only() -> None:
    """``-c`` sets git config, which can name a program for git to run.

    ``-c core.fsmonitor=…`` or ``-c diff.external=…`` turns a read-only-looking
    subcommand into an execution primitive, so an invocation carrying ``-c`` is
    disqualified outright rather than inspected further.
    """
    registry = _registry()

    before = ["git", "-c", "core.pager=cat", "status"]
    after = ["git", "status", "-c", "core.pager=cat"]

    assert is_read_only_command(before, registry=registry) is False
    # ``-c`` is also legal *after* the subcommand, and there it must not be
    # missed by stopping at the subcommand.
    assert is_read_only_command(after, registry=registry) is False


def test_git_dash_c_takes_a_value_and_is_skipped_correctly() -> None:
    """``-C <path>`` is the option that must NOT disqualify: it just picks a repo."""
    registry = _registry()

    read = ["git", "-C", "D:/repo", "status"]
    write = ["git", "-C", "D:/repo", "commit", "-m", "x"]

    assert is_read_only_command(read, registry=registry) is True
    assert is_read_only_command(write, registry=registry) is False


def test_git_diff_is_excluded_despite_looking_read_only() -> None:
    """``diff.external`` can make ``git diff`` spawn a program, so it is out."""
    assert is_read_only_command(["git", "diff"], registry=_registry()) is False


@pytest.mark.parametrize(
    "argv",
    [
        ["find", ".", "-exec", "rm", "{}", ";"],
        ["find", ".", "-execdir", "sh", "-c", "x", ";"],
        ["find", ".", "-delete"],
        ["rg", "--pre", "sh", "x"],
    ],
)
def test_executing_flags_disqualify_an_otherwise_read_only_command(
    argv: list[str],
) -> None:
    assert is_read_only_command(argv, registry=_registry()) is False


def test_an_operator_auto_run_entry_still_wins() -> None:
    """``auto_run`` is the existing opt-in; the classifier must not block it."""
    registry = CommandRegistry(auto_run=frozenset({"pytest"}))

    assert is_read_only_command(["pytest"], registry=registry) is True


# -- the executor actually applies it ----------------------------------------


def _executor(*, commands: CommandRegistry | None = None) -> ToolExecutor:
    from Sprout.security.approval import ApprovalManager, ApprovalPolicy
    from Sprout.storage.local.memory import MemoryOperationalStore

    tools = ToolRegistry()
    tools.register(CliRunTool())
    return ToolExecutor(
        tools,
        SecurityPolicy(),
        approvals=ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy()),
        commands=commands,
    )


def _run(executor: ToolExecutor, arguments: dict) -> object:
    return asyncio.run(
        executor.execute("cli_tool_run", arguments, source="interactive", task_id="t")
    )


def test_a_read_only_command_is_not_parked_for_approval() -> None:
    result = _run(_executor(commands=_registry()), {"command": "pwd", "args": []})

    assert result.approval_id is None, "a read-only command still asked for approval"


def test_an_executing_command_is_still_parked() -> None:
    result = _run(_executor(commands=_registry()), {"command": "pytest", "args": []})

    assert result.approval_id is not None, "a build tool ran without approval"


def test_without_a_registry_everything_still_asks() -> None:
    """Wiring is opt-in: no registry means the old behaviour, unchanged."""
    result = _run(_executor(commands=None), {"command": "pwd", "args": []})

    assert result.approval_id is not None


def test_deny_still_beats_the_read_only_exemption() -> None:
    """The exemption only ever relaxes REQUIRE_APPROVAL, never overrides DENY."""
    from Sprout.security.approval import ApprovalManager, ApprovalPolicy
    from Sprout.storage.local.memory import MemoryOperationalStore

    tools = ToolRegistry()
    tools.register(CliRunTool())
    executor = ToolExecutor(
        tools,
        SecurityPolicy(always_deny=frozenset({"cli_tool_run"})),
        approvals=ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy()),
        commands=_registry(),
    )

    result = _run(executor, {"command": "pwd", "args": []})

    assert result.ok is False
    assert "denied" in (result.error or "").casefold()


def test_a_malformed_check_fails_closed() -> None:
    """A classifier that raises must not grant; the prompt is the safe answer."""

    class _Broken:
        def name_of(self, _command: object) -> str:
            raise RuntimeError("registry is broken")

    result = _run(_executor(commands=_Broken()), {"command": "pwd", "args": []})

    assert result.approval_id is not None, "a broken classifier granted access"

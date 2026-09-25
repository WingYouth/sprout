""" "Allow this whole class" must cover a name, and only where that is sound.

The prompt offered three choices, and the middle one promised the whole class —
but ``approve_similar`` only cleared ``single_use``, while matching stayed on
``tool + arguments_fingerprint + task_id``. So the grant covered exactly the one
invocation the operator had been shown: answering "this class" for
``sprout --help`` re-asked for ``sprout info``, and a session spent probing the
CLI raised the prompt once per subcommand (86 times in one recorded day).

Widening a grant to a name is a real loosening, so it is bounded on purpose:

* the build-tool allowlist stays per-invocation — ``pytest`` imports
  ``conftest.py``, ``make`` runs the Makefile, and in worktree mode that
  directory is exactly where the task just wrote;
* ``git`` stays per-invocation — one name for both ``git status`` and
  ``git push``;
* a denylisted name can never gain a second route in;
* "approve once" is untouched: ``single_use=True`` is never widened.

A record with no class to widen to must also *say* so, rather than offering a
choice that cannot be honoured.
"""

from __future__ import annotations

import asyncio

import pytest

from Sprout.cli.commands.chat import _APPROVAL_TEXT
from Sprout.security.approval import ApprovalManager, ApprovalPolicy, ApprovalStatus
from Sprout.security.commands import CommandRegistry
from Sprout.storage.local.memory import MemoryOperationalStore


def _manager() -> ApprovalManager:
    """A manager with a real registry, as ``SecurityLayer`` wires it."""
    return ApprovalManager(
        MemoryOperationalStore(),
        policy=ApprovalPolicy(),
        commands=CommandRegistry(),
    )


def _key(manager: ApprovalManager, command: str, *args: str) -> str:
    return manager.class_key_for(
        "cli_tool_run", {"command": command, "args": list(args), "cwd": "."}
    )


def _grant(manager: ApprovalManager, command: str, *args: str, widen: bool) -> str:
    """Approve one ``cli_tool_run`` the way the CLI handler does."""

    async def _run() -> str:
        arguments = {"command": command, "args": list(args), "cwd": "."}
        record = await manager.request(
            "cli_tool_run", arguments, task_id="t1", source="interactive"
        )
        if widen:
            record.single_use = False
            await manager.store.save_approval(record)
        await manager.decide(record.id, True, decided_by="cli", channel="cli")
        return record.class_key

    return asyncio.run(_run())


def _approved(manager: ApprovalManager, command: str, *args: str) -> bool:
    return asyncio.run(
        manager.is_approved(
            "cli_tool_run",
            {"command": command, "args": list(args), "cwd": "."},
            task_id="t1",
        )
    )


# -- which names may be classed ------------------------------------------------


def test_a_command_the_task_cannot_author_is_classed_by_name() -> None:
    """``sprout`` is the case that raised 23 prompts in one session."""
    manager = _manager()
    assert _key(manager, "sprout", "--help") == "sprout"
    assert _key(manager, "sprout", "--help") == _key(manager, "sprout", "info")


@pytest.mark.parametrize(
    "command",
    ["pytest", "make", "npm", "python", "uv", "node", "cargo", "cargo", "go"],
)
def test_build_tools_are_never_classed(command: str) -> None:
    """Each one loads a file from the working directory the task just wrote."""
    manager = _manager()
    assert _key(manager, command, "test") == ""


def test_git_is_never_classed() -> None:
    """One name for both ``git status`` and ``git push``."""
    manager = _manager()
    assert _key(manager, "git", "status") == ""
    assert _key(manager, "git", "push") == ""


def test_a_read_only_command_is_never_classed() -> None:
    """It already runs without a prompt, so a grant would add nothing."""
    manager = _manager()
    assert _key(manager, "pwd") == ""
    assert _key(manager, "ls", "-la") == ""


def test_an_auto_run_command_is_never_classed() -> None:
    """Same reasoning: it is already allowed to run unapproved."""
    manager = ApprovalManager(
        MemoryOperationalStore(),
        policy=ApprovalPolicy(),
        commands=CommandRegistry(auto_run=frozenset({"myscript"})),
    )
    assert _key(manager, "myscript") == ""


def test_a_denylisted_name_never_gains_a_class() -> None:
    """A denial must not be reachable a second way."""
    manager = ApprovalManager(
        MemoryOperationalStore(),
        policy=ApprovalPolicy(),
        commands=CommandRegistry(denylist=frozenset({"sprout"})),
    )
    assert _key(manager, "sprout", "--help") == ""


def test_without_a_registry_nothing_is_classed() -> None:
    """The fail-safe default: no registry means every grant stays exact."""
    manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())
    assert _key(manager, "sprout", "--help") == ""


def test_only_cli_tool_run_is_classed() -> None:
    """Other tools carry no command; their arguments are the unit."""
    manager = _manager()
    assert manager.class_key_for("git.commit", {"proposal_id": "p1"}) == ""


# -- matching ------------------------------------------------------------------


def test_a_class_grant_covers_a_different_subcommand() -> None:
    """The bug: answering "this class" re-asked for the next subcommand."""
    manager = _manager()
    _grant(manager, "sprout", "--help", widen=True)

    assert _approved(manager, "sprout", "info"), "a different subcommand re-asked"
    assert _approved(manager, "sprout", "storage", "status")
    assert _approved(manager, "sprout", "--help")


def test_a_class_grant_does_not_cover_another_command() -> None:
    """Widening to a name must not leak across names."""
    manager = _manager()
    _grant(manager, "sprout", "--help", widen=True)

    assert not _approved(manager, "mytool", "--help")


def test_a_class_grant_does_not_cross_tasks() -> None:
    """A grant stays bound to the task that asked for it."""
    manager = _manager()
    _grant(manager, "sprout", "--help", widen=True)

    assert not asyncio.run(
        manager.is_approved(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"], "cwd": "."},
            task_id="other-task",
        )
    )


def test_approve_once_is_never_widened() -> None:
    """"Yes, this turn only" must stay one exact invocation."""
    manager = _manager()
    _grant(manager, "sprout", "--help", widen=False)

    assert _approved(manager, "sprout", "--help"), "the exact call must still run"
    assert not _approved(manager, "sprout", "info"), "approve-once leaked to a sibling"


def test_an_unclassable_command_still_matches_exactly() -> None:
    """``pytest`` keeps working per-invocation, as before."""
    manager = _manager()
    _grant(manager, "pytest", "-q", widen=True)

    assert _approved(manager, "pytest", "-q")
    assert not _approved(manager, "pytest", "-x"), "a build tool was widened"


def test_a_class_grant_expires() -> None:
    """Widening is still bounded by the record's own expiry."""
    manager = _manager()
    _grant(manager, "sprout", "--help", widen=True)

    async def _expire() -> bool:
        records = await manager.store.list_approvals(ApprovalStatus.APPROVED)
        for record in records:
            record.expires_at = _past()
            await manager.store.save_approval(record)
        return await manager.is_approved(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"], "cwd": "."},
            task_id="t1",
        )

    assert asyncio.run(_expire()) is False


def _past():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) - timedelta(seconds=1)


# -- the prompt tells the truth ------------------------------------------------


def test_the_class_note_names_the_command() -> None:
    """A note that says "same fingerprint" beside a "whole class" choice lied."""
    for language, template in _APPROVAL_TEXT["similar_scope"].items():
        assert "{command}" in template, f"class note cannot name its scope: {language}"


def test_every_language_states_the_exact_scope() -> None:
    """The per-invocation note must exist in every supported language."""
    languages = {"zh", "zh-Hant", "en", "ja", "ko", "ru", "es", "pt"}
    assert languages <= set(_APPROVAL_TEXT["exact_scope"])

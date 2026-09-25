"""`approvals suggest` must propose names that policy can actually act on.

The feature reads the approval history and proposes commands the operator keeps
granting, so a repeated prompt can become a standing entry. Two defects made it
useless rather than merely untidy:

* One row was emitted per *approval record*, so nineteen grants for one tool
  produced nineteen identical rows — the list was 20 copies of ``cli_tool_run``.
* It proposed ``record.tool``. The command policy is keyed on ``argv[0]``
  (``git``, ``sprout``), matched by ``CommandRegistry.name_of``; a tool name
  like ``cli_tool_run`` matches no command, so applying the suggestion wrote an
  allowlist entry that could never fire.

Both are pinned here, plus the honesty requirement: a tool name that cannot be
acted on is reported as such rather than offered.
"""

from __future__ import annotations

import asyncio

from Sprout.security.approval import ApprovalManager, ApprovalPolicy
from Sprout.storage.local.memory import MemoryOperationalStore


def _manager() -> ApprovalManager:
    return ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())


def _suggest(manager: ApprovalManager, *, limit: int = 20) -> list[dict]:
    return asyncio.run(manager.suggest_allowlist(limit=limit))


def _grant(manager: ApprovalManager, tool: str, arguments: dict) -> None:
    """Approve one request the way the tool layer does."""

    async def _run() -> None:
        record = await manager.request(tool, arguments, source="interactive")
        await manager.decide(record.id, True, decided_by="cli-user", channel="cli")

    asyncio.run(_run())


# -- no duplicate rows -------------------------------------------------------


def test_one_tool_approved_many_times_yields_one_suggestion() -> None:
    """The bug: nineteen grants produced nineteen identical rows."""
    manager = _manager()
    for index in range(19):
        _grant(manager, "cli_tool_run", {"command": "sprout", "args": [f"cmd{index}"]})

    suggestions = _suggest(manager)
    names = [item["tool"] for item in suggestions]

    assert len(names) == len(set(names)), "the same command was suggested more than once"
    assert names.count("sprout") == 1
    assert suggestions[0]["approvals"] == 19


def test_different_commands_are_counted_separately() -> None:
    """Counts are per command, not pooled across everything that was approved."""
    manager = _manager()
    for _ in range(3):
        _grant(manager, "cli_tool_run", {"command": "alpha", "args": []})
    _grant(manager, "cli_tool_run", {"command": "pwd", "args": []})

    by_name = {item["tool"]: item["approvals"] for item in _suggest(manager)}

    assert by_name.get("alpha") == 3
    assert by_name.get("pwd") == 1


# -- the proposed name is a command, not a tool ------------------------------


def test_a_command_is_proposed_instead_of_the_tool_name() -> None:
    """``auto_run`` is keyed on argv[0]; a tool name can never match it."""
    manager = _manager()
    _grant(manager, "cli_tool_run", {"command": "sprout", "args": ["info"]})

    suggestions = _suggest(manager)

    assert [item["tool"] for item in suggestions] == ["sprout"]
    assert suggestions[0]["actionable"] is True


def test_the_tool_name_is_marked_not_actionable_when_nothing_else_is_known() -> None:
    """An old record has no ``action_summary``; say so instead of guessing."""
    manager = _manager()

    async def _run_legacy() -> None:
        # A record with no action_summary, as written before that field existed.
        from Sprout.security.approval import ApprovalRecord

        record = ApprovalRecord(tool="cli_tool_run", arguments_fingerprint="fp")
        await manager.store.save_approval(record)
        await manager.decide(record.id, True, decided_by="cli", channel="cli")

    asyncio.run(_run_legacy())

    suggestions = _suggest(manager)

    assert [item["tool"] for item in suggestions] == ["cli_tool_run"]
    assert suggestions[0]["actionable"] is False, (
        "a tool name was offered as something the allowlist could act on"
    )


def test_actionable_candidates_sort_before_the_rest() -> None:
    """The useful rows must not be pushed off the list by the unusable ones."""
    manager = _manager()

    async def _run_legacy_many() -> None:
        from Sprout.security.approval import ApprovalRecord

        for index in range(10):
            record = ApprovalRecord(
                tool="cli_tool_run", arguments_fingerprint=f"fp{index}"
            )
            await manager.store.save_approval(record)
            await manager.decide(record.id, True, decided_by="cli", channel="cli")

    asyncio.run(_run_legacy_many())
    _grant(manager, "cli_tool_run", {"command": "pwd", "args": []})

    suggestions = _suggest(manager, limit=2)

    assert suggestions[0]["tool"] == "pwd", "the only usable candidate was not first"
    assert suggestions[0]["actionable"] is True


# -- already-allowlisted names are not proposed twice ------------------------


def test_an_already_allowlisted_command_is_not_proposed() -> None:
    """Proposing it again would be noise: the entry already exists."""
    manager = _manager()
    _grant(manager, "cli_tool_run", {"command": "git", "args": ["status"]})

    names = [item["tool"] for item in _suggest(manager)]

    assert "git" not in names, "git is already in the default allowlist"
    # Sanity: the same shape of grant for a name that is NOT allowlisted does
    # get proposed, so the assertion above is about the allowlist and not about
    # approvals failing to register.
    _grant(manager, "cli_tool_run", {"command": "alpha", "args": []})
    assert "alpha" in [item["tool"] for item in _suggest(manager)]


def test_the_limit_is_respected() -> None:
    manager = _manager()
    for name in ("alpha", "beta", "gamma"):
        _grant(manager, "cli_tool_run", {"command": name, "args": []})

    assert len(_suggest(manager, limit=2)) == 2

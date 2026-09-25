"""An approval prompt must show what is being authorised.

The prompt identified the *tool* and nothing else. For ``cli_tool_run`` that is
not enough to decide anything: the grant covers a specific command line, and the
fingerprint that decides whether a later call reuses the grant is computed from
those arguments. Showing only the tool name asked an operator to authorise an
action they could not see — and when a second, seemingly identical prompt
appeared, there was no way to tell that the arguments (and therefore the
fingerprint) had changed.

These tests pin the two halves of that: the arguments are displayed, and
anything credential-shaped in them is masked before it reaches a terminal or a
durable store.
"""

from __future__ import annotations

from Sprout.cli.commands.chat import (
    _approval_action_lines,
    _print_approval_record,
    _format_tool_arguments,
)
from Sprout.security.approval import ApprovalManager, ApprovalPolicy
from Sprout.storage.local.memory import MemoryOperationalStore


class _Record:
    """Stands in for an ApprovalRecord without needing a store."""

    def __init__(self, tool: str, action_summary: str = "") -> None:
        self.tool = tool
        self.action_summary = action_summary


def _pending(name: str, **arguments: object) -> dict[str, object]:
    return {"name": name, "arguments": arguments}


# -- the command line is shown ------------------------------------------------


def test_a_command_line_is_shown_as_an_invocation() -> None:
    """Command-shaped tools read best as the command, not as JSON."""
    rendered = _format_tool_arguments(
        "cli_tool_run",
        {"command": "sprout", "args": ["project", "workspaces"]},
    )

    assert rendered.startswith("sprout project workspaces")
    assert "[" not in rendered, "the argument list should be flattened, not JSON"


def test_extra_arguments_ride_along() -> None:
    """``cwd``/``timeout`` change what runs, so they belong on the line."""
    rendered = _format_tool_arguments(
        "cli_tool_run",
        {"command": "pytest", "args": ["--version"], "timeout": 20},
    )

    assert "pytest --version" in rendered
    assert "timeout" in rendered


def test_a_non_command_tool_falls_back_to_json() -> None:
    rendered = _format_tool_arguments("file_write", {"path": "src/app.py"})

    assert "file_write" in rendered
    assert "src/app.py" in rendered


def test_the_prompt_shows_the_matching_pending_call() -> None:
    """The tool name alone is shown alongside the action it will take."""
    record = _Record("cli_tool_run")
    pending = [_pending("cli_tool_run", command="sprout", args=["info"])]

    lines = _approval_action_lines(record, pending)

    assert lines == ["sprout info"]


def test_calls_for_other_tools_are_not_shown() -> None:
    """A turn may park several calls; only this grant's tool is relevant."""
    record = _Record("cli_tool_run")
    pending = [
        _pending("cli_tool_run", command="sprout", args=["info"]),
        _pending("git_inspect", operation="status"),
    ]

    lines = _approval_action_lines(record, pending)

    assert lines == ["sprout info"]
    assert all("git_inspect" not in line for line in lines)


def test_it_falls_back_to_the_stored_summary() -> None:
    """A grant replayed from the store has no turn to read the calls from."""
    record = _Record("cli_tool_run", action_summary='{"command": "sprout"}')

    assert _approval_action_lines(record, ()) == ['{"command": "sprout"}']


def test_no_arguments_renders_nothing_rather_than_dashes() -> None:
    assert _approval_action_lines(_Record("cli_tool_run"), ()) == []


# -- secrets never reach the screen or the store ------------------------------


def test_a_token_in_the_arguments_is_masked_on_screen() -> None:
    record = _Record("cli_tool_run")
    pending = [
        _pending(
            "cli_tool_run",
            command="curl",
            args=["-H", "Authorization: Bearer sk-live-abcdef1234567890"],
        )
    ]

    rendered = " ".join(_approval_action_lines(record, pending))

    assert "sk-live-abcdef1234567890" not in rendered
    assert "[REDACTED]" in rendered


def test_the_stored_summary_is_masked_too() -> None:
    """The summary is durable — audit stream and observation store both keep it."""
    import asyncio

    async def _run() -> str:
        from Sprout.security.commands import CommandRegistry

        manager = ApprovalManager(
            MemoryOperationalStore(),
            policy=ApprovalPolicy(),
            commands=CommandRegistry(),
        )
        record = await manager.request(
            "cli_tool_run",
            {"command": "curl", "args": ["-H", "Authorization: Bearer sk-live-secret123"]},
            source="interactive",
        )
        return record.action_summary

    summary = asyncio.run(_run())

    assert "sk-live-secret123" not in summary
    assert "[REDACTED]" in summary


def test_the_summary_is_recorded_for_the_audit_trail() -> None:
    """So "what did this grant cover?" is answerable after the fact."""
    import asyncio

    async def _run() -> str:
        manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())
        record = await manager.request(
            "cli_tool_run",
            {"command": "sprout", "args": ["project", "workspaces"]},
            source="interactive",
        )
        return record.action_summary

    summary = asyncio.run(_run())

    assert "sprout" in summary
    assert "project" in summary


def test_reusable_approval_is_bound_to_session_user_source_and_class() -> None:
    """The "similar" option should skip repeats without becoming global."""
    import asyncio

    async def _run() -> tuple[bool, bool, bool, str, str]:
        from Sprout.security.commands import CommandRegistry

        manager = ApprovalManager(
            MemoryOperationalStore(),
            policy=ApprovalPolicy(),
            commands=CommandRegistry(),
        )
        first_args = {"command": "sprout", "args": ["project", "workspaces"]}
        record = await manager.request(
            "cli_tool_run",
            first_args,
            source="interactive",
            requested_by="cli-user",
            session_id="session-1",
        )
        record.single_use = False
        await manager.store.save_approval(record)
        await manager.decide(record.id, True, decided_by="cli-user", channel="cli")

        same_session_same_class = await manager.is_approved(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"]},
            requested_by="cli-user",
            source="interactive",
            session_id="session-1",
        )
        other_session = await manager.is_approved(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"]},
            requested_by="cli-user",
            source="interactive",
            session_id="session-2",
        )
        other_user = await manager.is_approved(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"]},
            requested_by="other-user",
            source="interactive",
            session_id="session-1",
        )
        return (
            same_session_same_class,
            other_session,
            other_user,
            record.session_id,
            record.approval_class,
        )

    same_session, other_session, other_user, session_id, approval_class = asyncio.run(
        _run()
    )

    assert same_session is True
    assert other_session is False
    assert other_user is False
    assert session_id == "session-1"
    assert approval_class == "sprout"


def test_the_fingerprint_is_unchanged_by_the_new_field() -> None:
    """Visibility must not alter matching: the same arguments still hash alike."""
    import asyncio

    arguments = {"command": "sprout", "args": ["info"]}

    async def _run() -> tuple[str, object]:
        manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())
        record = await manager.request("cli_tool_run", arguments, source="interactive")
        return record.arguments_fingerprint, manager

    fingerprint, manager = asyncio.run(_run())

    assert fingerprint == manager.fingerprint(arguments)


# -- the prompt is actually wired --------------------------------------------
#
# The tests above exercise the formatter directly, so they pass even if the
# prompt handler never calls it — a green suite over a dead code path. This one
# drives ``_handle_cli_approval_prompt`` end to end and reads what it printed.


def test_the_handler_prints_the_action_it_is_asking_about(capsys) -> None:
    """Drives the real handler: the arguments must reach the operator's screen."""
    import asyncio

    from Sprout.cli.commands import chat

    manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())

    class _Store:
        async def get_approval(self, approval_id: str):
            return await manager.store.get_approval(approval_id)

    class _Approvals:
        store = _Store()

    class _Runtime:
        approvals = _Approvals()

        async def decide_approval(self, *args, **kwargs):
            return None

        async def resume_pending_task(self, *args, **kwargs):
            raise LookupError("not resumed in this test")

    async def _drive() -> None:
        record = await manager.request(
            "cli_tool_run",
            {"command": "sprout", "args": ["project", "workspaces"]},
            source="interactive",
            requested_by="cli-user",
        )

        async def _deny(_record):  # answer "no" so nothing is decided
            return "reject"

        chat._prompt_approval_decision = _deny  # type: ignore[assignment]
        await chat._handle_cli_approval_prompt(
            _Runtime(),
            "session-1",
            {
                "approval_required": True,
                "approval_ids": [record.id],
                "pending_tool_calls": [
                    {
                        "name": "cli_tool_run",
                        "arguments": {
                            "command": "sprout",
                            "args": ["project", "workspaces"],
                        },
                    }
                ],
            },
            "cli-user",
        )

    asyncio.run(_drive())

    printed = capsys.readouterr().out
    assert "cli_tool_run" in printed
    assert "sprout project workspaces" in printed, (
        "the handler printed the tool name without the command it would run"
    )


def test_cli_approval_resumes_a_session_exactly_once(monkeypatch) -> None:
    """The CLI owns the resume and must not race Runtime's session callback."""
    import asyncio
    from types import SimpleNamespace

    from Sprout.cli.commands import chat

    manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())
    calls = {"resume": 0}

    class _Store:
        async def get_approval(self, approval_id: str):
            return await manager.store.get_approval(approval_id)

        async def save_approval(self, record):
            await manager.store.save_approval(record)

    class _Runtime:
        approvals = SimpleNamespace(store=_Store())

        async def decide_approval(self, approval_id, approved, **kwargs):
            assert kwargs["resume_session"] is False
            await manager.decide(approval_id, approved, decided_by="cli-user")

        async def resume_pending_task(self, *_args, **_kwargs):
            calls["resume"] += 1
            return SimpleNamespace(content="continued", metadata={})

    async def _approve(_record):
        return "approve"

    monkeypatch.setattr(chat, "_prompt_approval_decision", _approve)
    monkeypatch.setattr(chat, "_render_cli_markdown", lambda _content: None)
    monkeypatch.setattr(chat, "_print_reply_meta", lambda _metadata: None)
    monkeypatch.setattr(chat, "_print_session_separator", lambda: None)

    async def _drive() -> None:
        record = await manager.request(
            "cli_tool_run",
            {"command": "sprout", "args": ["info"]},
            source="interactive",
            requested_by="cli-user",
            session_id="session-1",
        )
        await chat._handle_cli_approval_prompt(
            _Runtime(),
            "session-1",
            {"approval_required": True, "approval_ids": [record.id]},
            "cli-user",
        )

    asyncio.run(_drive())
    assert calls["resume"] == 1


def test_chained_approvals_print_one_session_separator(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from Sprout.cli.commands import chat

    manager = ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())
    separators = []
    approvals = []

    class _Runtime:
        class _Approvals:
            store = manager.store

        approvals = _Approvals()

        def __init__(self):
            self.resumes = 0

        async def decide_approval(self, approval_id, approved, **kwargs):
            assert kwargs["resume_session"] is False
            await manager.decide(approval_id, approved, decided_by="cli-user")

        async def resume_pending_task(self, *_args, **_kwargs):
            self.resumes += 1
            metadata = (
                {"approval_required": True, "approval_ids": [approvals[1].id]}
                if self.resumes == 1
                else {}
            )
            return SimpleNamespace(
                content="continued", metadata=metadata, session_id="session-1"
            )

    async def _approve(_record):
        return "approve"

    monkeypatch.setattr(chat, "_prompt_approval_decision", _approve)
    monkeypatch.setattr(chat, "_render_cli_markdown", lambda _content: None)
    monkeypatch.setattr(chat, "_print_reply_meta", lambda _metadata: None)
    monkeypatch.setattr(chat, "_print_session_separator", lambda: separators.append(1))

    async def _drive():
        for index in range(2):
            approvals.append(
                await manager.request(
                    "cli_tool_run",
                    {"command": "sprout", "args": [str(index)]},
                    source="interactive",
                    requested_by="cli-user",
                    session_id="session-1",
                )
            )
        runtime = _Runtime()
        await chat._handle_cli_approval_prompt(
            runtime,
            "session-1",
            {"approval_required": True, "approval_ids": [approvals[0].id]},
            "cli-user",
        )
        assert runtime.resumes == 2

    asyncio.run(_drive())
    assert separators == [1]


def test_the_approval_block_keeps_borders_aligned_with_cjk(capsys) -> None:
    from datetime import UTC, datetime
    from Sprout.security.approval import ApprovalRecord

    record = ApprovalRecord(
        tool="cli_tool_run",
        arguments_fingerprint="fp",
        id="d83d105c-77b2-4619-8a10-84e1438c8670",
        session_id="c2fac9c2-7f55-48a3-a49c-4799c49b8378",
        approval_class="sprout",
        requested_by="cli-user",
        source="interactive",
        expires_at=datetime(2026, 9, 24, 13, 13, 59, tzinfo=UTC),
    )

    _print_approval_record(
        record,
        [{"name": "cli_tool_run", "arguments": {"command": "sprout", "args": ["skills", "--help"]}}],
    )

    printed = capsys.readouterr().out
    framed = [line for line in printed.splitlines() if line.startswith("| ")]

    assert framed
    assert all(line.endswith(" |") for line in framed)

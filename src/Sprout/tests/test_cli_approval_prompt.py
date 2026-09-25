from __future__ import annotations

from types import SimpleNamespace

import pytest

from Sprout.cli import approval_prompt


@pytest.mark.asyncio
async def test_async_approval_uses_the_shared_selectable_decisions(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        approval_prompt.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )

    class _Question:
        async def ask_async(self):
            return approval_prompt.APPROVE_SIMILAR

    def _select(message, *, choices, style):
        captured.update(message=message, choices=choices, style=style)
        return _Question()

    monkeypatch.setattr(approval_prompt.questionary, "select", _select)

    result = await approval_prompt.ask_approval("permission required", allow_similar=True)

    assert result == approval_prompt.APPROVE_SIMILAR
    assert [choice.value for choice in captured["choices"]] == [
        approval_prompt.APPROVE,
        approval_prompt.APPROVE_SIMILAR,
        approval_prompt.REJECT,
        approval_prompt.DEFER,
    ]


@pytest.mark.asyncio
async def test_async_approval_offers_explicit_failing_verification_override(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        approval_prompt.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )

    class _Question:
        async def ask_async(self):
            return approval_prompt.APPROVE_WITH_FAILURES

    def _select(message, *, choices, style):
        captured.update(message=message, choices=choices, style=style)
        return _Question()

    monkeypatch.setattr(approval_prompt.questionary, "select", _select)

    result = await approval_prompt.ask_approval(
        "verification failed", allow_failures=True, yes_no=True
    )

    assert result == approval_prompt.APPROVE_WITH_FAILURES
    assert [choice.value for choice in captured["choices"]] == [
        approval_prompt.APPROVE_WITH_FAILURES,
        approval_prompt.REJECT,
    ]
    assert [choice.title for choice in captured["choices"]] == ["是", "否"]


@pytest.mark.asyncio
async def test_binary_approval_uses_yes_no_and_regular_approve(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        approval_prompt.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )

    class _Question:
        async def ask_async(self):
            return approval_prompt.APPROVE

    def _select(message, *, choices, style):
        captured.update(message=message, choices=choices, style=style)
        return _Question()

    monkeypatch.setattr(approval_prompt.questionary, "select", _select)

    result = await approval_prompt.ask_approval("apply changes?", yes_no=True)

    assert result == approval_prompt.APPROVE
    assert [choice.title for choice in captured["choices"]] == ["是", "否"]


@pytest.mark.asyncio
async def test_async_approval_does_not_prompt_without_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(
        approval_prompt.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: False),
    )
    monkeypatch.setattr(
        approval_prompt.questionary,
        "select",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-interactive stdin must not open a prompt")
        ),
    )

    assert await approval_prompt.ask_approval("approval") is None


def test_sync_approval_uses_the_same_decisions_and_optional_stop(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        approval_prompt.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )

    class _Question:
        def ask(self):
            return approval_prompt.QUIT

    def _select(message, *, choices, style):
        captured.update(message=message, choices=choices, style=style)
        return _Question()

    monkeypatch.setattr(approval_prompt.questionary, "select", _select)

    result = approval_prompt.ask_approval_sync(
        "task approval", allow_similar=True, allow_quit=True
    )

    assert result == approval_prompt.QUIT
    assert [choice.value for choice in captured["choices"]] == [
        approval_prompt.APPROVE,
        approval_prompt.APPROVE_SIMILAR,
        approval_prompt.REJECT,
        approval_prompt.DEFER,
        approval_prompt.QUIT,
    ]

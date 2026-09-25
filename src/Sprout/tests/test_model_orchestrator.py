"""Tests for model retry and fallback orchestration."""

from __future__ import annotations

import asyncio

import pytest

from Sprout.llm.messages import LLMMessage, LLMResponse
from Sprout.llm.orchestrator import ModelOrchestrationError, ModelOrchestrator


class _Provider:
    name = "fake"

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, messages, *, tools=()):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _NonRetryableError(Exception):
    pass


class _StreamingProvider(_Provider):
    async def stream(self, messages, *, tools=()):
        for chunk in ("alpha", "beta"):
            yield chunk


def test_retries_then_succeeds() -> None:
    provider = _Provider(
        [RuntimeError("transient"), LLMResponse(content="ok")]
    )
    orchestrator = ModelOrchestrator([provider])

    result = asyncio.run(orchestrator.chat([LLMMessage.user("hi")]))

    assert result.content == "ok"
    assert provider.calls == 2


def test_falls_back_to_next_provider() -> None:
    first = _Provider([RuntimeError("down")])
    second = _Provider([LLMResponse(content="fallback")])
    second.name = "backup"
    orchestrator = ModelOrchestrator([first, second], max_attempts=1)

    result = asyncio.run(orchestrator.chat([LLMMessage.user("hi")]))

    assert result.content == "fallback"
    assert first.calls == 1
    assert second.calls == 1


def test_raises_when_all_fail() -> None:
    orchestrator = ModelOrchestrator(
        [_Provider([RuntimeError("bad")]), _Provider([RuntimeError("also bad")])],
        max_attempts=1,
    )

    with pytest.raises(ModelOrchestrationError) as excinfo:
        asyncio.run(orchestrator.chat([LLMMessage.user("hi")]))

    assert len(excinfo.value.failures) == 2


def test_streams_from_primary_provider() -> None:
    orchestrator = ModelOrchestrator([_StreamingProvider([LLMResponse(content="")])])

    chunks = asyncio.run(_collect(orchestrator.stream([LLMMessage.user("hi")])))

    assert chunks == ["alpha", "beta"]


def test_stream_falls_back_to_chat_when_provider_has_no_stream() -> None:
    orchestrator = ModelOrchestrator(
        [_Provider([LLMResponse(content="single")])]
    )

    chunks = asyncio.run(_collect(orchestrator.stream([LLMMessage.user("hi")])))

    assert chunks == ["single"]


def test_does_not_retry_non_retryable_errors() -> None:
    provider = _Provider([_NonRetryableError("bad input")])
    orchestrator = ModelOrchestrator(
        [provider],
        max_attempts=3,
        non_retryable_exception_types=(_NonRetryableError,),
    )

    with pytest.raises(ModelOrchestrationError):
        asyncio.run(orchestrator.chat([LLMMessage.user("hi")]))

    assert provider.calls == 1
    assert len(orchestrator.metrics) == 1
    assert orchestrator.metrics[0].retryable is False


async def _collect(chunks):
    return [chunk async for chunk in chunks]

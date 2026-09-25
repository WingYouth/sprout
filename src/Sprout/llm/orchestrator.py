"""Multi-provider retry and fallback for model calls."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from Sprout.llm.base import ModelProvider
from Sprout.llm.client import invoke_model
from Sprout.llm.messages import LLMMessage, LLMResponse, LLMStreamEvent
from Sprout.llm.usage import get_usage_recorder

if TYPE_CHECKING:
    from Sprout.tools.spec import ToolSpec

_DEFAULT_STREAM_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Provider-level retry and fallback policy."""

    max_attempts: int = 2
    delay_seconds: float = 0.0
    backoff_factor: float = 2.0
    retryable_exception_types: tuple[type[Exception], ...] = ()
    non_retryable_exception_types: tuple[type[Exception], ...] = ()

    def should_retry(self, exc: Exception) -> bool:
        if self.non_retryable_exception_types and isinstance(
            exc, self.non_retryable_exception_types
        ):
            return False
        if self.retryable_exception_types and not isinstance(
            exc, self.retryable_exception_types
        ):
            return False
        return True


@dataclass(frozen=True, slots=True)
class ModelAttempt:
    provider: str
    attempt: int
    error: str
    duration_seconds: float
    retryable: bool


class ModelOrchestrationError(RuntimeError):
    """Raised when every provider attempt fails."""

    def __init__(self, failures: Sequence[tuple[str, str]]) -> None:
        self.failures = tuple(failures)
        detail = "; ".join(f"{name}: {error}" for name, error in failures)
        super().__init__(f"All model providers failed: {detail}")


class ModelOrchestrator:
    """Try providers in order, retrying each before moving to the next.

    The orchestrator implements :class:`ModelProvider`, so ``AgentLoop`` and
    ``ModelAgent`` do not need to know whether they hold one provider or a
    fallback chain.
    """

    name = "model-orchestrator"

    def __init__(
        self,
        providers: Sequence[ModelProvider],
        *,
        max_attempts: int = 2,
        retry_delay_seconds: float = 0.0,
        backoff_factor: float = 2.0,
        retryable_exception_types: Sequence[type[Exception]] = (),
        non_retryable_exception_types: Sequence[type[Exception]] = (),
    ) -> None:
        if not providers:
            raise ValueError("ModelOrchestrator requires at least one provider")
        self._providers = tuple(providers)
        self._policy = RetryPolicy(
            max_attempts=max(1, max_attempts),
            delay_seconds=max(0.0, retry_delay_seconds),
            backoff_factor=max(1.0, backoff_factor),
            retryable_exception_types=tuple(retryable_exception_types),
            non_retryable_exception_types=tuple(non_retryable_exception_types),
        )
        self.metrics: list[ModelAttempt] = []

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolSpec] = (),
    ) -> LLMResponse:
        failures: list[tuple[str, str]] = []
        for provider in self._providers:
            for attempt in range(1, self._policy.max_attempts + 1):
                started = time.monotonic()
                try:
                    return await invoke_model(provider, messages, tools=tools)
                except Exception as exc:  # noqa: BLE001 - retry/fallback boundary
                    retryable = self._policy.should_retry(exc)
                    self.metrics.append(
                        ModelAttempt(
                            provider=provider.name,
                            attempt=attempt,
                            error=f"{type(exc).__name__}: {exc}",
                            duration_seconds=time.monotonic() - started,
                            retryable=retryable,
                        )
                    )
                    get_usage_recorder().record_attempt(
                        provider=provider.name,
                        model=getattr(provider, "model", "unknown"),
                        attempt=attempt,
                        error=f"{type(exc).__name__}: {exc}",
                        duration_seconds=self.metrics[-1].duration_seconds,
                        retryable=retryable,
                    )
                    failures.append((provider.name, _failure_text(exc)))
                    if not retryable or attempt == self._policy.max_attempts:
                        break
                    delay = self._policy.delay_seconds * (
                        self._policy.backoff_factor ** (attempt - 1)
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
        raise ModelOrchestrationError(failures)
    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolSpec] = (),
    ):
        """Stream from the primary provider, falling back to a single chat call."""
        provider = self._providers[0]
        stream = getattr(provider, "stream", None)
        if stream is None:
            response = await self.chat(messages, tools=tools)
            yield response.text
            return
        yielded = False
        iterator = stream(messages, tools=tools).__aiter__()
        timeout = _stream_timeout_seconds(provider)
        while True:
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                await _close_async_iterator(iterator)
                if not yielded:
                    response = await self.chat(messages, tools=tools)
                    yield response.text
                    return
                raise RuntimeError(
                    f"Model stream timed out after {timeout:g}s waiting for more data"
                ) from exc
            yielded = True
            yield chunk

    async def stream_events(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolSpec] = (),
    ):
        """Stream structured events from the primary provider."""
        provider = self._providers[0]
        stream_events = getattr(provider, "stream_events", None)
        if stream_events is None:
            response = await self.chat(messages, tools=tools)
            yield LLMStreamEvent(
                content=response.text,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
                usage=response.usage,
            )
            return
        yielded = False
        iterator = stream_events(messages, tools=tools).__aiter__()
        timeout = _stream_timeout_seconds(provider)
        while True:
            try:
                event = await asyncio.wait_for(iterator.__anext__(), timeout)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                await _close_async_iterator(iterator)
                if not yielded:
                    response = await self.chat(messages, tools=tools)
                    yield LLMStreamEvent(
                        content=response.text,
                        tool_calls=response.tool_calls,
                        finish_reason=response.finish_reason,
                        usage=response.usage,
                    )
                    return
                raise RuntimeError(
                    f"Model stream timed out after {timeout:g}s waiting for more data"
                ) from exc
            yielded = True
            yield event


async def _close_async_iterator(iterator: object) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


def _stream_timeout_seconds(provider: ModelProvider) -> float:
    configured = getattr(provider, "timeout_seconds", None)
    try:
        timeout = float(configured)
    except (TypeError, ValueError):
        return _DEFAULT_STREAM_TIMEOUT_SECONDS
    if timeout <= 0:
        return _DEFAULT_STREAM_TIMEOUT_SECONDS
    return min(timeout, _DEFAULT_STREAM_TIMEOUT_SECONDS)


def _failure_text(exc: Exception) -> str:
    """Preserve nested provider errors instead of reporting only a generic wrapper."""
    details = [f"{type(exc).__name__}: {exc}"]
    for nested in getattr(exc, "errors", ()):
        nested_text = f"{type(nested).__name__}: {nested}"
        cause = getattr(nested, "cause", None)
        if cause is not None:
            nested_text += f"; cause={type(cause).__name__}: {cause}"
        details.append(nested_text)
    return " | ".join(details)


__all__ = ["ModelOrchestrationError", "ModelOrchestrator"]

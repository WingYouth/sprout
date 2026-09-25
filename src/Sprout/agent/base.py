"""Vendor-neutral agent protocol: an agent only sees Message and AgentContext."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from Sprout.llm.client import invoke_model
from Sprout.llm.messages import LLMMessage
from Sprout.session.models import Turn

if TYPE_CHECKING:
    from Sprout.context.context import AgentContext
    from Sprout.llm.base import ModelProvider
    from Sprout.message.models import Message


@dataclass(frozen=True, slots=True)
class AgentResult:
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    async def run(self, message: Message, context: AgentContext) -> AgentResult: ...


def _with_memory(context: AgentContext) -> list[LLMMessage]:
    """Turn history, prefixed by the memory block when there is one.

    The block carries the parts of ``ContextMemory`` that are not turns —
    summary, curated facts, recalled snippets. Iterating the object yields only
    the working window, so without this leading system message those parts never
    reached the model.
    """
    from Sprout.memory.snapshot import memory_block_for

    messages: list[LLMMessage] = []
    block = memory_block_for(context.memory)
    if block:
        messages.append(LLMMessage.system(block))
    messages.extend(history_messages(context.memory))
    return messages


def history_messages(memory: Sequence[Turn] | object) -> list[LLMMessage]:
    """Convert stored turns into LLM chat messages.

    Accepts a ``Sequence[Turn]`` (legacy) or a :class:`ContextMemory`, whose
    ``__iter__`` yields the working turns in chronological order.
    """
    messages: list[LLMMessage] = []
    for turn in memory:
        role = getattr(turn, "role", None)
        content = getattr(turn, "content", None)
        if role is None or content is None:
            continue
        if role == "user":
            messages.append(LLMMessage.user(content))
        elif role == "assistant":
            messages.append(LLMMessage.assistant(content))
    return messages


@dataclass(slots=True)
class ModelAgent:
    """Single-shot agent: one model call, no tool loop."""

    model: ModelProvider

    async def run(self, message: Message, context: AgentContext) -> AgentResult:
        messages = _with_memory(context)
        messages.append(LLMMessage.user(message.content))
        response = await invoke_model(self.model, messages)
        return AgentResult(
            content=response.text,
            metadata={"finish_reason": response.finish_reason, "model": response.model},
        )

    async def stream(self, message: Message, context: AgentContext):
        """Stream the single-shot answer as text chunks."""
        messages = _with_memory(context)
        messages.append(LLMMessage.user(message.content))
        stream = getattr(self.model, "stream", None)
        if stream is not None:
            async for chunk in stream(messages):
                if chunk:
                    yield chunk
            return
        response = await invoke_model(self.model, messages)
        if response.text:
            yield response.text

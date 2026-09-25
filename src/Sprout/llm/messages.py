"""Chat message primitives exchanged with model providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation requested by the model."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> LLMMessage:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> LLMMessage:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(
        cls, content: str | None = None, tool_calls: tuple[ToolCall, ...] = ()
    ) -> LLMMessage:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, name: str, content: str) -> LLMMessage:
        return cls(
            role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name
        )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    model: str | None = None
    usage: Usage = field(default_factory=Usage)

    @property
    def text(self) -> str:
        return self.content or ""


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    """One structured increment from a streaming provider.

    Content and tool calls are emitted separately: content deltas stream as
    they arrive, while the complete ``tool_calls`` tuple is emitted once on the
    final event.
    """

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: Usage | None = None

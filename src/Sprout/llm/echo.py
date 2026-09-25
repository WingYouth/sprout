"""Dependency-free echo provider used by smoke tests and offline defaults."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from Sprout.llm.messages import LLMMessage, LLMResponse, Role

if TYPE_CHECKING:
    from Sprout.tools.spec import ToolSpec


class EchoModel:
    """Returns the last user message with a prefix; requires no network or key."""

    def __init__(self, *, prefix: str = "Echo: ", name: str = "echo") -> None:
        self.name = name
        self.prefix = prefix

    async def chat(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ) -> LLMResponse:
        last_user = next((m for m in reversed(messages) if m.role is Role.USER), None)
        if last_user is not None and last_user.content is not None:
            text = last_user.content
        elif messages and messages[-1].content is not None:
            text = messages[-1].content
        else:
            text = ""
        return LLMResponse(content=f"{self.prefix}{text}", finish_reason="stop", model=self.name)

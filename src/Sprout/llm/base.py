"""Vendor-neutral model provider protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from Sprout.llm.messages import LLMMessage, LLMResponse

if TYPE_CHECKING:
    from Sprout.tools.spec import ToolSpec


class ModelProvider(Protocol):
    """A chat-completion backend. Implementations are added as adapters.

    ``tools`` receives uniform :class:`ToolSpec` objects; providers that do not
    support tool calling may ignore them.
    """

    name: str

    async def chat(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ) -> LLMResponse: ...

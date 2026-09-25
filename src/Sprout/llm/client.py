"""Central entry point for every model call in the runtime.

Agent code must not call ``provider.chat()`` directly; it uses this small
facade so all model traffic goes through the ``Sprout.llm`` package.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from Sprout.llm.messages import LLMMessage, LLMResponse
from Sprout.llm.usage import get_usage_recorder

if TYPE_CHECKING:
    from Sprout.llm.base import ModelProvider
    from Sprout.tools.spec import ToolSpec


async def invoke_model(
    provider: ModelProvider,
    messages: Sequence[LLMMessage],
    *,
    tools: Sequence[ToolSpec] = (),
) -> LLMResponse:
    """Invoke one model provider through the uniform LLM contract."""
    response = await provider.chat(messages, tools=tools)
    get_usage_recorder().record(
        provider=getattr(provider, "name", "unknown"),
        model=response.model or getattr(provider, "model", "unknown"),
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
    )
    return response

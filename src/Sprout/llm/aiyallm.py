"""``aiyallm`` model adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from aiyallm import Aiyallm
from aiyallm import OpenAICompatibleProvider as AiyallmOpenAICompatibleProvider

from Sprout.llm.messages import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    Role,
    ToolCall,
    Usage,
)

if TYPE_CHECKING:
    from Sprout.tools.spec import ToolSpec


class AiyallmProvider:
    """Adapt the ``aiyallm`` package to the Sprout :class:`ModelProvider` protocol."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        name: str = "aiyallm",
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        providers: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.api_key_env = api_key_env
        self.last_usage: Usage | None = None

        resolved_key = api_key
        if not resolved_key and api_key_env:
            resolved_key = os.environ.get(api_key_env)
        if providers:
            # Preserve provider names and model lists for refs such as
            # ``deepseek/deepseek-flash``.
            self._client = Aiyallm(
                providers=[dict(item) for item in providers],
                default_model=self.model or None,
            )
        else:
            provider = AiyallmOpenAICompatibleProvider(
                "aiyallm-openai-compatible",
                api_key=resolved_key,
                api_key_required=False,
                base_url=self.base_url,
                models=[self.model],
                timeout=self.timeout_seconds,
                allow_unknown_models=True,
            )
            self._client = Aiyallm(providers=[provider], default_model=self.model)

    async def chat(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ) -> LLMResponse:
        """Call the configured model through the ``aiyallm`` package."""
        encoded_messages = [self._encode_message(message) for message in messages]
        encoded_tools = [self._encode_tool(spec) for spec in tools] if tools else None

        response = await self._client.achat(
            messages=encoded_messages,
            model=self.model,
            temperature=self.temperature,
            tools=encoded_tools,
        )

        tool_calls = tuple(
            ToolCall(
                id=call.id,
                name=call.name,
                arguments=call.arguments_dict,
            )
            for call in response.tool_calls
        )
        return LLMResponse(
            content=response.content or "",
            tool_calls=tool_calls,
            finish_reason=response.finish_reason,
            model=response.model or self.model,
            usage=self._decode_usage(response.usage),
        )

    async def stream(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ):
        encoded_messages = [self._encode_message(message) for message in messages]
        encoded_tools = [self._encode_tool(spec) for spec in tools] if tools else None
        async for chunk in self._client.astream(
            messages=encoded_messages,
            model=self.model,
            temperature=self.temperature,
            tools=encoded_tools,
        ):
            if chunk.usage is not None:
                self.last_usage = self._decode_usage(chunk.usage)
            yield chunk.content or ""

    async def stream_events(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ):
        """Stream structured events from ``aiyallm`` chat chunks."""
        encoded_messages = [self._encode_message(message) for message in messages]
        encoded_tools = [self._encode_tool(spec) for spec in tools] if tools else None
        async for chunk in self._client.astream(
            messages=encoded_messages,
            model=self.model,
            temperature=self.temperature,
            tools=encoded_tools,
        ):
            if chunk.usage is not None:
                self.last_usage = self._decode_usage(chunk.usage)
            if chunk.content:
                yield LLMStreamEvent(content=chunk.content)
            if chunk.tool_calls:
                yield LLMStreamEvent(
                    tool_calls=tuple(
                        ToolCall(
                            id=call.id,
                            name=call.name,
                            arguments=call.arguments_dict,
                        )
                        for call in chunk.tool_calls
                    ),
                    finish_reason=chunk.finish_reason,
                    usage=(
                        self._decode_usage(chunk.usage)
                        if chunk.usage is not None
                        else None
                    ),
                )


    @staticmethod
    def _encode_tool(spec: ToolSpec) -> dict[str, Any]:
        parameters = dict(spec.input_schema) if spec.input_schema else {
            "type": "object",
            "properties": {},
        }
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": parameters,
            },
        }

    @staticmethod
    def _encode_message(message: LLMMessage) -> dict[str, Any]:
        encoded: dict[str, Any] = {"role": message.role.value}
        if message.content is not None:
            encoded["content"] = message.content
        if message.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            dict(call.arguments), ensure_ascii=False, default=str
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role is Role.TOOL:
            encoded["tool_call_id"] = message.tool_call_id
            if message.name:
                encoded["name"] = message.name
        return encoded

    @staticmethod
    def _decode_usage(usage: Any) -> Usage:
        return Usage(
            prompt_tokens=int(getattr(usage, "input_tokens", 0)),
            completion_tokens=int(getattr(usage, "output_tokens", 0)),
            total_tokens=int(
                getattr(
                    usage,
                    "total_tokens",
                    getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0),
                )
            ),
        )

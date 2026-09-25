"""OpenAI-compatible chat-completions adapter (OpenAI, DeepSeek, Moonshot, ...)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx

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


class ModelAuthError(RuntimeError):
    """Raised when the provider was constructed without a usable API key."""


class OpenAICompatibleProvider:
    """Talks to any ``/chat/completions`` endpoint using the OpenAI wire format."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        name: str = "openai_compatible",
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    async def chat(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ) -> LLMResponse:
        if not self.api_key:
            raise ModelAuthError(
                f"Provider {self.name!r} has no API key; set it via an environment variable "
                "(see Sprout.security.secrets.resolve_api_key)"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._encode_message(m) for m in messages],
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = [self._encode_tool(spec) for spec in tools]

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Model request failed with HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )
            data = response.json()
        return self._decode_response(data)

    async def stream(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ):
        """Stream completion text deltas from a chat-completions endpoint."""
        if not self.api_key:
            raise ModelAuthError(
                f"Provider {self.name!r} has no API key; set it via an environment variable "
                "(see Sprout.security.secrets.resolve_api_key)"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._encode_message(m) for m in messages],
            "stream": True,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = [self._encode_tool(spec) for spec in tools]

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Model request failed with HTTP {response.status_code}: "
                        f"{body[:500]}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    async def stream_events(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ):
        """Stream structured events, including accumulated tool-call deltas."""
        if not self.api_key:
            raise ModelAuthError(
                f"Provider {self.name!r} has no API key; set it via an environment variable "
                "(see Sprout.security.secrets.resolve_api_key)"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._encode_message(m) for m in messages],
            "stream": True,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = [self._encode_tool(spec) for spec in tools]

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        tool_deltas: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage = Usage()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Model request failed with HTTP {response.status_code}: "
                        f"{body[:500]}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield LLMStreamEvent(content=content)
                    for raw_call in delta.get("tool_calls") or []:
                        index = int(raw_call.get("index", 0))
                        entry = tool_deltas.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        if raw_call.get("id"):
                            entry["id"] = raw_call["id"]
                        function = raw_call.get("function") or {}
                        if function.get("name"):
                            entry["name"] += function["name"]
                        if function.get("arguments"):
                            entry["arguments"] += function["arguments"]
                    usage_data = chunk.get("usage")
                    if usage_data:
                        usage = Usage(
                            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
                            completion_tokens=int(
                                usage_data.get("completion_tokens", 0)
                            ),
                            total_tokens=int(usage_data.get("total_tokens", 0)),
                        )

        tool_calls = tuple(
            ToolCall(
                id=entry["id"] or str(index),
                name=entry["name"],
                arguments=_parse_stream_arguments(entry["arguments"]),
            )
            for index, entry in sorted(tool_deltas.items())
        )
        yield LLMStreamEvent(
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
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
    def _decode_response(data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices") or [{}]
        choice = choices[0]
        message = choice.get("message") or {}
        raw_calls = message.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for raw in raw_calls:
            function = raw.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
            except json.JSONDecodeError:
                arguments = {"_raw": raw_arguments}
            tool_calls.append(
                ToolCall(
                    id=raw.get("id") or "",
                    name=function.get("name") or "",
                    arguments=arguments,
                )
            )
        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
            completion_tokens=int(usage_data.get("completion_tokens", 0)),
            total_tokens=int(usage_data.get("total_tokens", 0)),
        )
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tuple(tool_calls),
            finish_reason=choice.get("finish_reason"),
            model=data.get("model"),
            usage=usage,
        )


def _parse_stream_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            return {"value": arguments}
        return arguments
    except json.JSONDecodeError:
        return {"_raw": raw}

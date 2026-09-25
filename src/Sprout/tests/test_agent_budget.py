"""Tests for AgentLoop model/tool call budgets."""

from __future__ import annotations

import pytest

from Sprout.agent.base import ModelAgent
from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.context.context import AgentContext
from Sprout.llm.messages import LLMResponse, LLMStreamEvent, ToolCall, Usage
from Sprout.message.models import Message
from Sprout.session.models import Session
from Sprout.tests.conftest import EchoTool, ScriptedModel
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec


class PromptCapturingModel:
    name = "prompt-capturing"

    def __init__(self) -> None:
        self.system_prompt = ""

    async def chat(self, messages, *, tools=()):
        self.system_prompt = str(messages[0].content or "")
        return LLMResponse(content="ok", finish_reason="stop")


class FailingAfterToolModel:
    name = "failing-after-tool"

    async def chat(self, messages, *, tools=()):
        raise RuntimeError("provider down")


def _context(metadata: dict) -> AgentContext:
    return AgentContext(
        session=Session(id="s1", user_id="u1"),
        user={"id": "u1"},
        metadata=metadata,
    )


def _context_with_tools(metadata: dict, tools: dict) -> AgentContext:
    return AgentContext(
        session=Session(id="s1", user_id="u1"),
        user={"id": "u1"},
        tools=tools,
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_loop_respects_model_call_budget() -> None:
    tool_call = LLMResponse(
        content=None,
        tool_calls=(ToolCall(id="c", name="echo_tool", arguments={"text": "x"}),),
        finish_reason="tool_calls",
    )
    model = ScriptedModel([tool_call] * 5)
    tools = ToolRegistry()
    tools.register(EchoTool())
    loop = AgentLoop(
        model=model,
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    result = await loop.run(
        Message("go"),
        _context({"task_budget": {"max_model_calls": 1}}),
    )

    assert result.metadata["model_calls"] == 1
    assert result.metadata["truncated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "label"),
    [
        ("zh", "中文"),
        ("zh-Hant", "繁體中文"),
        ("en", "English"),
        ("ja", "日本語"),
        ("ko", "한국어"),
        ("ru", "Русский"),
        ("es", "Español"),
        ("pt", "Português"),
    ],
)
async def test_loop_uses_configured_response_language_over_input_detection(
    language: str,
    label: str,
) -> None:
    model = PromptCapturingModel()
    loop = AgentLoop(model=model)

    result = await loop.run(
        Message(
            "scan project structure",
            metadata={"cli_language": language},
        ),
        _context({}),
    )

    assert result.content == "ok"
    assert f"Answer in language '{label}'" in model.system_prompt
    assert "progress/status text" in model.system_prompt


@pytest.mark.asyncio
async def test_loop_caps_tool_calls() -> None:
    tool_calls = LLMResponse(
        content=None,
        tool_calls=(
            ToolCall(id="a", name="echo_tool", arguments={"text": "1"}),
            ToolCall(id="b", name="echo_tool", arguments={"text": "2"}),
            ToolCall(id="c", name="echo_tool", arguments={"text": "3"}),
        ),
        finish_reason="tool_calls",
    )
    model = ScriptedModel([tool_calls, LLMResponse(content="done", finish_reason="stop")])
    tool = EchoTool()
    tools = ToolRegistry()
    tools.register(tool)
    loop = AgentLoop(
        model=model,
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    result = await loop.run(
        Message("go"),
        _context({"task_budget": {"max_tool_calls": 2}}),
    )

    assert result.content == "done"
    assert result.metadata["tool_calls"] == 2
    assert len(tool.seen) == 2


@pytest.mark.asyncio
async def test_loop_respects_token_budget() -> None:
    model = ScriptedModel(
        [
            LLMResponse(
                content="answer",
                finish_reason="stop",
                usage=Usage(prompt_tokens=90, completion_tokens=10, total_tokens=100),
            )
        ]
    )
    loop = AgentLoop(model=model)

    result = await loop.run(
        Message("go"),
        _context({"task_budget": {"max_tokens": 50}}),
    )

    assert result.metadata["truncated"] is True


class _StreamModel:
    name = "stream-model"

    async def chat(self, messages, *, tools=()):
        return LLMResponse(content="streamed", finish_reason="stop")

    async def stream(self, messages, *, tools=()):
        for chunk in ("hel", "lo"):
            yield chunk


@pytest.mark.asyncio
async def test_model_agent_streams_text_chunks() -> None:
    agent = ModelAgent(model=_StreamModel())
    context = _context({})

    chunks = []
    async for chunk in agent.stream(Message("hi"), context):
        chunks.append(chunk)

    assert "".join(chunks) == "hello"


class _StreamToolModel:
    name = "stream-tool-model"

    def __init__(self) -> None:
        self.calls = 0

    async def stream_events(self, messages, *, tools=()):
        self.calls += 1
        if self.calls == 1:
            yield LLMStreamEvent(content="thinking ")
            yield LLMStreamEvent(
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="echo_tool",
                        arguments={"text": "hi"},
                    ),
                )
            )
        else:
            yield LLMStreamEvent(content="done")


@pytest.mark.asyncio
async def test_loop_streams_and_executes_tool_calls() -> None:
    tool = EchoTool()
    tools = ToolRegistry()
    tools.register(tool)
    model = _StreamToolModel()
    loop = AgentLoop(
        model=model,
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    chunks = []
    async for chunk in loop.stream(
        Message("go"),
        _context_with_tools({}, {"echo_tool": tool}),
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "thinking done"
    assert tool.seen == [{"text": "hi"}]
    assert model.calls == 2


class _ApprovalTool:
    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="needs_approval",
            description="Requests approval.",
            input_schema={"type": "object", "properties": {}},
            risk_level="low",
        )

    async def invoke(self, arguments):
        return ToolResult.needs_approval("approval-1")


@pytest.mark.asyncio
async def test_loop_stops_when_tool_requires_approval() -> None:
    tool = _ApprovalTool()
    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(id="a", name="needs_approval", arguments={}),
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    loop = AgentLoop(
        model=model,
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    result = await loop.run(
        Message("go"),
        _context_with_tools({}, {"needs_approval": tool}),
    )

    assert result.metadata["approval_required"] is True
    assert result.metadata["approval_ids"] == ["approval-1"]
    assert result.metadata["pending_tool_calls"] == [
        {"id": "a", "name": "needs_approval", "arguments": {}}
    ]


@pytest.mark.asyncio
async def test_identical_tool_calls_in_one_batch_execute_once() -> None:
    from Sprout.agent.executor import ToolCallOutcome

    class _Executor:
        def __init__(self) -> None:
            self.calls = []

        async def run_calls_detailed(self, calls, **_kwargs):
            self.calls.extend(calls)
            return [
                ToolCallOutcome(call=calls[0], result=ToolResult.success("ok"))
            ]

    executor = _Executor()
    loop = AgentLoop(model=PromptCapturingModel(), executor=executor)
    calls = (
        ToolCall(
            id="call-1",
            name="cli_tool_run",
            arguments={"command": "sprout", "args": ["info"]},
        ),
        ToolCall(
            id="call-2",
            name="cli_tool_run",
            arguments={"args": ["info"], "command": "sprout"},
        ),
    )

    messages, tool_count, approval_ids, _summary = await loop._execute_tool_calls(
        calls,
        requested_by="operator",
        tool_calls=0,
        budget_tool_calls=0,
    )

    assert len(executor.calls) == 1
    assert tool_count == 1
    assert approval_ids == []
    assert [(message.tool_call_id, message.content) for message in messages] == [
        ("call-1", "ok"),
        ("call-2", "ok"),
    ]


@pytest.mark.asyncio
async def test_loop_resumes_pending_tool_calls() -> None:
    tool = EchoTool()
    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel([LLMResponse(content="resumed", finish_reason="stop")])
    loop = AgentLoop(
        model=model,
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    result = await loop.run(
        Message("continue"),
        _context_with_tools(
            {
                "resume_tool_calls": [
                    {
                        "id": "c1",
                        "name": "echo_tool",
                        "arguments": {"text": "resume"},
                    }
                ]
            },
            {"echo_tool": tool},
        ),
    )

    assert result.content == "resumed"
    assert tool.seen == [{"text": "resume"}]


@pytest.mark.asyncio
async def test_loop_returns_tool_result_when_model_fails_after_resume() -> None:
    tool = EchoTool()
    tools = ToolRegistry()
    tools.register(tool)
    loop = AgentLoop(
        model=FailingAfterToolModel(),
        executor=ActionExecutor(tools=ToolExecutor(tools=tools)),
    )

    result = await loop.run(
        Message(
            "continue",
            metadata={"cli_language": "zh"},
        ),
        _context_with_tools(
            {
                "resume_tool_calls": [
                    {
                        "id": "c1",
                        "name": "echo_tool",
                        "arguments": {"text": "resume"},
                    }
                ]
            },
            {"echo_tool": tool},
        ),
    )

    assert result.metadata["degraded"] is True
    assert "工具已执行" in result.content
    assert "echo: resume" in result.content
    assert "provider down" in result.content

"""Runtime online-path tests: turns, tool loop, middleware, failure isolation."""

from __future__ import annotations

import pytest

from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.context.builder import ContextBuilder
from Sprout.events.types import AGENT_COMPLETED, MESSAGE_SENT
from Sprout.llm.messages import LLMResponse, ToolCall
from Sprout.llm.registry import ModelRegistry
from Sprout.message.models import Message, OutboundMessage
from Sprout.runtime.middleware import MiddlewareChain, NoopMiddleware
from Sprout.runtime.runtime import Runtime
from Sprout.security.approval import ApprovalManager
from Sprout.session.models import Session
from Sprout.skills.registry import SkillRegistry
from Sprout.storage.bundle import StorageBundle
from Sprout.tests.conftest import EchoTool, ScriptedModel, build_runtime
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_runtime_handles_turn_and_persists_history() -> None:
    runtime, _ = build_runtime()
    await runtime.start()

    reply = await runtime.handle(Message("hello", channel="cli", user_id="u-1"))

    assert reply.content == "Echo: hello"
    assert reply.channel == "cli"
    assert reply.session_id
    turns = await runtime.history(reply.session_id)
    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert turns[0].content == "hello"
    await runtime.stop()


@pytest.mark.asyncio
async def test_resume_pending_requires_previous_approval() -> None:
    runtime, _ = build_runtime()
    await runtime.start()
    session = await runtime.create_session("u-1")

    with pytest.raises(LookupError):
        await runtime.resume_pending(session.id, user_id="u-1")

    await runtime.stop()


@pytest.mark.asyncio
async def test_resume_pending_task_continues_without_new_user_turn() -> None:
    tool = EchoTool(risk_level="high")
    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="echo_tool",
                        arguments={"text": "resume"},
                    ),
                ),
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done after approval", finish_reason="stop"),
        ]
    )
    storage = StorageBundle.in_memory()
    approvals = ApprovalManager(storage.operational)
    runtime, _ = build_runtime(
        storage=storage,
        model=model,
        tools=tools,
        approvals=approvals,
    )
    await runtime.start()

    first = await runtime.handle(Message("run the risky tool", channel="cli", user_id="u-1"))
    assert first.metadata["approval_required"] is True
    assert tool.seen == []

    pending = await approvals.pending()
    assert len(pending) == 1
    assert pending[0].session_id == first.session_id
    await approvals.decide(pending[0].id, True, decided_by="u-1")

    resumed = await runtime.resume_pending_task(first.session_id, user_id="u-1")

    assert resumed.content == "done after approval"
    assert tool.seen == [{"text": "resume"}]
    turns = await runtime.history(first.session_id)
    assert [turn.role for turn in turns] == ["user", "assistant", "assistant"]
    assert [turn.content for turn in turns if turn.role == "user"] == [
        "run the risky tool"
    ]
    await runtime.stop()


@pytest.mark.asyncio
async def test_decide_approval_resumes_chat_session() -> None:
    tool = EchoTool(risk_level="high")
    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="c1",
                        name="echo_tool",
                        arguments={"text": "after approval"},
                    ),
                ),
                finish_reason="tool_calls",
            ),
            LLMResponse(content="continued", finish_reason="stop"),
        ]
    )
    storage = StorageBundle.in_memory()
    approvals = ApprovalManager(storage.operational)
    runtime, _ = build_runtime(
        storage=storage,
        model=model,
        tools=tools,
        approvals=approvals,
    )
    await runtime.start()

    first = await runtime.handle(Message("run risky", channel="cli", user_id="u-1"))
    pending = await approvals.pending()

    decided = await runtime.decide_approval(
        pending[0].id,
        True,
        decided_by="u-1",
        channel="web",
    )

    assert decided.session_id == first.session_id
    assert tool.seen == [{"text": "after approval"}]
    turns = await runtime.history(first.session_id)
    assert [turn.role for turn in turns] == ["user", "assistant", "assistant"]
    assert turns[-1].content == "continued"
    await runtime.stop()


@pytest.mark.asyncio
async def test_streaming_approval_returns_metadata_without_legacy_text() -> None:
    tool = EchoTool(risk_level="high")
    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel(
        [
            LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(id="c1", name="echo_tool", arguments={"text": "approval"}),
                ),
                finish_reason="tool_calls",
            ),
        ]
    )
    storage = StorageBundle.in_memory()
    approvals = ApprovalManager(storage.operational)
    runtime, _ = build_runtime(
        storage=storage,
        model=model,
        tools=tools,
        approvals=approvals,
    )
    await runtime.start()

    chunks = [
        chunk
        async for chunk in runtime.handle_stream(
            Message("run risky tool", channel="cli", user_id="u-1")
        )
    ]

    text = "".join(chunk.content for chunk in chunks)
    outbound = next(chunk.outbound for chunk in chunks if chunk.outbound is not None)
    assert "This action requires human approval" not in text
    assert outbound.metadata["approval_required"] is True
    assert len(outbound.metadata["approval_ids"]) == 1
    assert outbound.metadata["pending_tool_calls"][0]["name"] == "echo_tool"
    await runtime.stop()


@pytest.mark.asyncio
async def test_agent_loop_executes_tools_until_final_answer() -> None:
    tool = EchoTool()
    from Sprout.tools.registry import ToolRegistry

    tools = ToolRegistry()
    tools.register(tool)
    model = ScriptedModel(
        [
            LLMResponse(
                content=None,
                tool_calls=(ToolCall(id="c1", name="echo_tool", arguments={"text": "hi"}),),
                finish_reason="tool_calls",
            ),
            LLMResponse(content="All done", finish_reason="stop"),
        ]
    )
    runtime, _ = build_runtime(model=model, tools=tools)

    reply = await runtime.handle(Message("use the tool"))

    assert reply.content == "All done"
    assert tool.seen == [{"text": "hi"}]
    turns = await runtime.history(reply.session_id)
    assert turns[-1].content == "All done"


@pytest.mark.asyncio
async def test_loop_stops_at_max_steps() -> None:
    endless_tool_call = LLMResponse(
        content=None,
        tool_calls=(ToolCall(id="c", name="echo_tool", arguments={"text": "again"}),),
        finish_reason="tool_calls",
    )
    model = ScriptedModel([endless_tool_call] * 10)
    tools = ToolRegistry()
    tools.register(EchoTool())
    executor = ToolExecutor(tools=tools)
    loop = AgentLoop(model=model, executor=ActionExecutor(tools=executor), max_steps=3)
    runtime = Runtime(
        storage=StorageBundle.in_memory(),
        models=ModelRegistry(),
        tools=tools,
        skills=SkillRegistry(),
    )
    runtime.register_agent("assistant", loop, default=True)

    context = await ContextBuilder(runtime.storage).build(
        message=Message("spin"),
        session=Session(id="s1", user_id="u1"),
        tools=runtime.tools.list(),
        skills=runtime.skills.list(),
    )
    result = await loop.run(Message("spin"), context)
    assert result.metadata["steps"] == 3
    assert result.metadata["truncated"] is True


@pytest.mark.asyncio
async def test_middleware_before_and_after_are_applied() -> None:
    runtime, _ = build_runtime()

    class TaggingMiddleware:
        async def before(self, message: Message) -> Message:
            object.__setattr__(message, "metadata", {**message.metadata, "tagged": True})
            return message

        async def after(self, message: Message, outbound: OutboundMessage) -> OutboundMessage:
            return OutboundMessage(
                content=outbound.content + " [mw]",
                channel=outbound.channel,
                session_id=outbound.session_id,
                correlation_id=outbound.correlation_id,
                metadata=outbound.metadata,
            )

    runtime.middleware.add(TaggingMiddleware())
    reply = await runtime.handle(Message("hello"))
    assert reply.content == "Echo: hello [mw]"


@pytest.mark.asyncio
async def test_failing_subscriber_does_not_break_the_turn() -> None:
    runtime, _ = build_runtime()

    async def broken(event) -> None:
        raise OSError("observer offline")

    runtime.events.subscribe("*", broken)
    reply = await runtime.handle(Message("still works"))
    assert reply.content == "Echo: still works"


@pytest.mark.asyncio
async def test_events_flow_for_one_turn() -> None:
    runtime, _ = build_runtime()
    seen: list[str] = []
    runtime.events.subscribe("*", lambda event: seen.append(event.name))

    await runtime.handle(Message("hi"))

    assert AGENT_COMPLETED in seen
    assert MESSAGE_SENT in seen


@pytest.mark.asyncio
async def test_handle_stream_finishes_without_stopasynciteration_value() -> None:
    runtime, _ = build_runtime()

    chunks = [chunk async for chunk in runtime.handle_stream(Message("hello stream"))]

    assert [chunk.content for chunk in chunks if chunk.content] == ["Echo: hello stream"]
    assert chunks[-1].outbound is not None
    assert chunks[-1].outbound.content == "Echo: hello stream"


@pytest.mark.asyncio
async def test_middleware_chain_order() -> None:
    chain = MiddlewareChain(middlewares=(NoopMiddleware(),))
    message = Message("x")
    assert (await chain.before(message)).content == "x"


@pytest.mark.asyncio
async def test_startup_settles_approvals_that_lapsed_while_closed() -> None:
    """An approval whose TTL ran out must not stay PENDING across a restart.

    ``sweep_expired`` existed but nothing called it — the only route was an
    operator running ``sprout approvals sweep``. So a lapsed grant stayed
    pending indefinitely, and every consumer of "what is waiting on a human"
    counted it: nine had accumulated, one of them prompting each new session to
    answer a question whose task was long gone.
    """
    from datetime import UTC, datetime, timedelta

    from Sprout.security.approval import ApprovalStatus

    runtime, _ = build_runtime()
    record = await runtime.approvals.request(
        "skill.install", {"name": "x"}, source="interactive"
    )
    record.expires_at = datetime.now(UTC) - timedelta(hours=2)
    await runtime.approvals.store.save_approval(record)
    assert await runtime.pending_approvals() == [record], "premise: it starts pending"

    await runtime.start()

    assert await runtime.pending_approvals() == [], "a lapsed grant survived startup"
    settled = await runtime.approvals.store.get_approval(record.id)
    assert settled is not None and settled.status is ApprovalStatus.EXPIRED


@pytest.mark.asyncio
async def test_startup_leaves_a_live_approval_alone() -> None:
    """Sweeping at startup must not settle a grant that is still usable."""
    runtime, _ = build_runtime()
    record = await runtime.approvals.request(
        "skill.install", {"name": "x"}, source="interactive"
    )

    await runtime.start()

    assert [item.id for item in await runtime.pending_approvals()] == [record.id]

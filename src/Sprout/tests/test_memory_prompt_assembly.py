"""What the model actually receives from the memory layer.

``ContextMemory`` is not just a list of turns: it also carries the session
summary, the curated facts, and the recalled snippets. Only the turns were
reachable by iterating it, and ``history_messages`` — the one place both agents
build their message list from — iterated it, so the other three parts were
composed on every turn, persisted for audit, and then never sent. The model
answered with no recall of anything outside the current working window.

``render_snapshot`` already produced exactly the block the prompt needed (its
module docstring says the block "is fed to the model as part of the system
prompt"); it was only ever used to warm a cache and write an audit record.
"""

from __future__ import annotations

from Sprout.agent.base import history_messages
from Sprout.memory.models import ContextMemory, SearchHit, SessionFact
from Sprout.memory.snapshot import memory_block_for
from Sprout.session.models import Session, Turn


def _memory(**overrides) -> ContextMemory:
    base = {
        "session": Session(id="s1", user_id="u"),
        "working": (Turn(session_id="s1", role="user", content="working turn"),),
    }
    base.update(overrides)
    return ContextMemory(**base)  # type: ignore[arg-type]


def test_facts_and_recalled_reach_the_model_block() -> None:
    """The two parts a working window cannot express."""
    memory = _memory(
        facts=(SessionFact(session_id="s1", key="name", value="Ada"),),
        recalled=(
            SearchHit(session_id="s1", turn_seq=3, turn_id="t3", snippet="earlier detail"),
        ),
    )

    block = memory_block_for(memory)

    assert "Ada" in block, "a curated fact never reached the prompt"
    assert "earlier detail" in block, "a recalled snippet never reached the prompt"


def test_a_summary_reaches_the_model_block() -> None:
    from Sprout.memory.models import SessionSummary

    memory = _memory(
        summary=SessionSummary(
            session_id="s1",
            seq=1,
            covered_through=5,
            content="the user is debugging storage",
        )
    )

    assert "debugging storage" in memory_block_for(memory)


def test_an_empty_memory_adds_no_system_message() -> None:
    """No curated memory means no block — the prompt must not grow for nothing."""
    assert memory_block_for(_memory()) == ""


def test_a_plain_turn_sequence_is_not_treated_as_memory() -> None:
    """``history_messages`` also accepts a bare sequence of turns."""
    turns = [Turn(session_id="s1", role="user", content="hi")]

    assert memory_block_for(turns) == ""


def test_history_messages_still_yields_the_working_window() -> None:
    """The turn path is unchanged: this helper is additive."""
    memory = _memory(
        facts=(SessionFact(session_id="s1", key="name", value="Ada"),),
    )

    messages = history_messages(memory)

    assert [m.content for m in messages] == ["working turn"]


def test_the_agent_loop_sends_the_memory_block() -> None:
    """End to end through ``AgentLoop``'s message assembly.

    Drives the real loop with a recording model so the assertion is about what
    would have been sent, not about a helper the loop might not call.
    """
    import asyncio
    from typing import Any

    from Sprout.agent.loop import AgentLoop
    from Sprout.context.context import AgentContext
    from Sprout.llm.messages import LLMResponse
    from Sprout.message.models import Message

    sent: list[Any] = []

    class _Recorder:
        async def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
            sent.append(messages)
            return LLMResponse(content="ok", finish_reason="stop", model="fake")

    memory = _memory(
        facts=(SessionFact(session_id="s1", key="name", value="Ada"),),
    )
    context = AgentContext(session=Session(id="s1", user_id="u"), memory=memory)
    message = Message(content="who am i", channel="cli", user_id="u", session_id="s1")

    asyncio.run(AgentLoop(model=_Recorder()).run(message, context))

    assert sent, "the loop never called the model"
    contents = [m.content for m in sent[0]]
    assert any("Ada" in content for content in contents), (
        "the loop did not put the memory block in front of the model"
    )

"""Node tools are scoped to their node, not registered globally.

Each execution node used to register its tools in the process-wide
ToolRegistry and unregister them in a ``finally``. With nodes running
concurrently, node A's teardown could remove a tool node B was still
executing — and because ``context.tools`` (what the model is shown) and the
registry (what actually runs) are separate, the failure surfaced as
"Unknown tool" for a tool the model had just been told existed.

These tests pin the replacement: node tools travel as a per-call overlay.
"""

from __future__ import annotations

import asyncio
from typing import Any

from Sprout.agent.executor import ActionExecutor
from Sprout.llm.messages import ToolCall
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec

NAME = "sandbox_read_file"


class _Tool:
    """A tool that reports which instance handled the call."""

    def __init__(self, tag: str) -> None:
        self.spec = ToolSpec(
            name=NAME,
            description="test tool",
            input_schema={"type": "object", "properties": {}},
            risk_level="low",
        )
        self.tag = tag

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.success(self.tag)


def _call(call_id: str = "c1", name: str = NAME) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


async def _run(executor: ActionExecutor, call: ToolCall) -> str:
    outcomes = await executor.run_calls_detailed([call])
    return outcomes[0].result.to_text()


def test_node_tools_execute_without_global_registration() -> None:
    """A node's tool must run even though the registry never hears about it."""
    registry = ToolRegistry()
    executor = ActionExecutor(tools=ToolExecutor(tools=registry))
    scoped = executor.with_scoped_tools({NAME: _Tool("node")})

    assert asyncio.run(_run(scoped, _call())) == "node"
    # The whole point: nothing was registered process-wide.
    assert not registry.contains(NAME)


def test_concurrent_nodes_keep_their_own_tool_instances() -> None:
    """Two nodes sharing a tool *name* must each get their own instance."""
    registry = ToolRegistry()
    executor = ActionExecutor(tools=ToolExecutor(tools=registry))

    async def run() -> list[str]:
        node_a = executor.with_scoped_tools({NAME: _Tool("A")})
        node_b = executor.with_scoped_tools({NAME: _Tool("B")})
        return list(await asyncio.gather(_run(node_a, _call()), _run(node_b, _call())))

    assert asyncio.run(run()) == ["A", "B"]


def test_scoping_falls_back_to_the_registry() -> None:
    """Tools outside the node scope still resolve, as they did before."""
    registry = ToolRegistry()
    global_tool = _Tool("global")
    global_tool.spec = ToolSpec(
        name="global_tool",
        description="d",
        input_schema={"type": "object", "properties": {}},
        risk_level="low",
    )
    registry.register(global_tool)
    scoped = ActionExecutor(tools=ToolExecutor(tools=registry)).with_scoped_tools(
        {NAME: _Tool("node")}
    )

    assert asyncio.run(_run(scoped, _call(name="global_tool"))) == "global"


def test_scoped_copy_does_not_leak_into_the_original_executor() -> None:
    """Scoping must be a copy, since the agent instance is shared."""
    registry = ToolRegistry()
    base = ActionExecutor(tools=ToolExecutor(tools=registry))

    base.with_scoped_tools({NAME: _Tool("node")})

    # The original still has no node scope: a missing tool stays missing.
    outcomes = asyncio.run(base.run_calls_detailed([_call()]))
    assert not outcomes[0].result.ok
    assert "Unknown tool" in outcomes[0].result.to_text()

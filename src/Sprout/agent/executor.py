"""ActionExecutor: runs model-requested tool calls and shapes LLM tool messages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from Sprout.llm.messages import LLMMessage, ToolCall
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.result import ToolResult


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    call: ToolCall
    result: ToolResult

    @property
    def requires_approval(self) -> bool:
        return self.result.approval_id is not None


class ActionExecutor:
    """Bounded fan-out of tool calls through the security-gated ToolExecutor."""

    def __init__(self, tools: ToolExecutor, *, max_actions_per_step: int = 8) -> None:
        self._tools = tools
        self._max_actions = max_actions_per_step

    def with_scoped_tools(self, node_tools: Mapping[str, Any]) -> ActionExecutor:
        """A copy that dispatches this node's tools before the registry.

        A copy, not a mutation: the agent is shared across nodes, so scoping
        state must travel with the call rather than live on the executor.
        """
        return ActionExecutor(
            self._tools.with_scoped_tools(node_tools),
            max_actions_per_step=self._max_actions,
        )

    async def run_calls(
        self,
        calls: Sequence[ToolCall],
        *,
        requested_by: str = "unknown",
        session_id: str = "",
    ) -> list[LLMMessage]:
        messages: list[LLMMessage] = []
        for outcome in await self.run_calls_detailed(
            calls, requested_by=requested_by, session_id=session_id
        ):
            messages.append(
                LLMMessage.tool_result(
                    outcome.call.id,
                    outcome.call.name,
                    outcome.result.to_text(),
                )
            )
        for call in calls[self._max_actions :]:
            messages.append(
                LLMMessage.tool_result(
                    call.id, call.name, "Skipped: too many tool calls in one step"
                )
            )
        return messages

    async def run_calls_detailed(
        self,
        calls: Sequence[ToolCall],
        *,
        requested_by: str = "unknown",
        session_id: str = "",
    ) -> list[ToolCallOutcome]:
        outcomes: list[ToolCallOutcome] = []
        for call in calls[: self._max_actions]:
            result = await self._tools.execute(
                call.name,
                call.arguments,
                requested_by=requested_by,
                session_id=session_id,
            )
            outcomes.append(ToolCallOutcome(call=call, result=result))
        return outcomes

    async def run_call(
        self,
        call: ToolCall,
        *,
        requested_by: str = "unknown",
        session_id: str = "",
    ) -> ToolResult:
        return await self._tools.execute(
            call.name,
            call.arguments,
            requested_by=requested_by,
            session_id=session_id,
        )

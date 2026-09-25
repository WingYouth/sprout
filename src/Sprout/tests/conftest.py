"""Shared fixtures for runtime tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.llm.echo import EchoModel
from Sprout.llm.messages import LLMResponse, Role
from Sprout.llm.registry import ModelRegistry
from Sprout.runtime.runtime import Runtime
from Sprout.security.approval import ApprovalManager
from Sprout.security.policy import SecurityPolicy
from Sprout.skills.registry import SkillRegistry
from Sprout.storage.bundle import StorageBundle
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry, create_tool_registry
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec


class ScriptedModel:
    """Returns queued responses in order; a test double for ModelProvider."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.name = "scripted"
        self.responses = list(responses)
        self.calls: list[int] = []

    async def chat(self, messages, *, tools=()) -> LLMResponse:
        first = messages[0] if messages else None
        if (
            first is not None
            and first.role is Role.SYSTEM
            and first.content
            and "Classify the user's intent" in first.content
        ):
            text = "\n".join(str(message.content or "") for message in messages)
            intent = (
                "task"
                if any(term in text for term in ("task", "fix", "修复", "任务"))
                else "conversation"
            )
            return LLMResponse(
                content=json.dumps(
                    {"intent": intent, "confidence": 0.9, "reason": "test classifier"}
                ),
                finish_reason="stop",
                model=self.name,
            )
        self.calls.append(len(messages))
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="done", finish_reason="stop")


@dataclass
class EchoTool:
    """A low-risk test tool."""

    seen: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = "low"

    def __post_init__(self) -> None:
        self.spec = ToolSpec(
            name="echo_tool",
            description="Echoes its input back.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            risk_level=self.risk_level,
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.seen.append(dict(arguments))
        return ToolResult.success(f"echo: {arguments.get('text', '')}")


def build_runtime(
    *,
    storage: StorageBundle | None = None,
    model=None,
    tools: ToolRegistry | None = None,
    approvals: ApprovalManager | None = None,
    agent=None,
) -> tuple[Runtime, ToolExecutor]:
    """Assemble a runtime with in-memory storage and an echo/scripted model."""
    storage = storage or StorageBundle.in_memory()
    tools = tools if tools is not None else create_tool_registry(storage)
    model = model or EchoModel()
    executor = ToolExecutor(
        tools=tools,
        policy=SecurityPolicy(),
        approvals=approvals,
    )
    runtime = Runtime(
        storage=storage,
        models=ModelRegistry(),
        tools=tools,
        skills=SkillRegistry(),
    )
    runtime.models.register(model, default=True)
    runtime.register_agent(
        "assistant",
        agent
        or AgentLoop(model=model, executor=ActionExecutor(tools=executor), max_steps=4),
        default=True,
    )
    return runtime, executor


@pytest.fixture
def echo_runtime() -> Runtime:
    runtime, _ = build_runtime()
    return runtime

"""Shared fixtures for runtime tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.llm.echo import EchoModel
from Sprout.llm.messages import LLMResponse
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
        self.calls.append(len(messages))
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="done", finish_reason="stop")


class TestIntentRecognizer:
    """Small deterministic intent recognizer for tests; production uses laya."""

    def classify(self, state):
        text = str(state.get("message") or "")
        intent = "conversation"
        confidence = 0.9
        if any(term in text for term in ("批准", "同意", "拒绝", "approval")):
            intent = "approval"
        elif any(term in text for term in ("记住", "忘记", "memory")):
            intent = "memory"
        elif any(term in text for term in ("技能", "沉淀", "evolution", "growth")):
            intent = "evolution"
        elif any(term in text for term in ("下载", "运行构建", "命令", "tool")):
            intent = "tool"
        elif any(
            term in text
            for term in ("删除", "删掉", "移除", "消失", "delete", "remove")
        ):
            intent = "delete"
            confidence = 0.93
        elif any(
            term in text
            for term in ("执行任务", "修复", "实现", "敲", "写", "task", "fix")
        ):
            intent = "task"
        elif any(term in text for term in ("入口文件", "项目", "工作区", "workspace")):
            intent = "workspace"
        return {
            "intent": intent,
            "trigger_event": f"intent.{intent}.requested",
            "confidence": confidence,
            "reason": "test_laya_recognizer",
        }


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
    intent_recognizer=None,
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
    runtime._intent_recognizer = intent_recognizer or TestIntentRecognizer()  # noqa: SLF001
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

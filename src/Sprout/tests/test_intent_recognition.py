"""Intent recognition tests."""

from __future__ import annotations

import json

import pytest

from Sprout.events.types import (
    INTENT_APPROVAL_REQUESTED,
    INTENT_CONVERSATION_REQUESTED,
    INTENT_EVOLUTION_REQUESTED,
    INTENT_MEMORY_REQUESTED,
    INTENT_RECOGNIZED,
    INTENT_TASK_REQUESTED,
    INTENT_TOOL_REQUESTED,
    INTENT_WORKSPACE_REQUESTED,
)
from Sprout.llm.messages import LLMResponse, Role
from Sprout.message.models import Message
from Sprout.runtime.runtime import _project_analyze_tool_call
from Sprout.storage.bundle import StorageBundle
from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.embeddings import HashingEmbedder
from Sprout.storage.lanes import CONTEXT_SNAPSHOTS_NS
from Sprout.tests.conftest import ScriptedModel, build_runtime

INPUT_OUTPUT_CASES = [
    ("请执行任务：修复测试", "task", INTENT_TASK_REQUESTED),
    ("查一下这个项目的入口文件", "workspace", INTENT_WORKSPACE_REQUESTED),
    ("记住我喜欢中文回复", "memory", INTENT_MEMORY_REQUESTED),
    ("批准刚才那个操作", "approval", INTENT_APPROVAL_REQUESTED),
    ("下载依赖并运行构建", "tool", INTENT_TOOL_REQUESTED),
    ("把这次失败沉淀成一个技能", "evolution", INTENT_EVOLUTION_REQUESTED),
    ("你好，介绍一下你自己", "conversation", INTENT_CONVERSATION_REQUESTED),
]


class InputOutputIntentModel:
    """LLM test double for direct input/output intent cases."""

    name = "input-output-intent"

    async def chat(self, messages, *, tools=()):
        first = messages[0] if messages else None
        if (
            first is not None
            and first.role is Role.SYSTEM
            and first.content
            and "Classify the user's intent" in first.content
        ):
            prompt = str(messages[-1].content or "")
            raw_input = prompt.split("Input:\n", 1)[-1]
            try:
                text = str(json.loads(raw_input).get("message") or "")
            except json.JSONDecodeError:
                text = prompt
            intent = "conversation"
            if any(term in text for term in ("批准", "同意", "拒绝", "approval")):
                intent = "approval"
            elif any(term in text for term in ("记住", "忘记", "memory")):
                intent = "memory"
            elif any(term in text for term in ("技能", "沉淀", "evolution", "growth")):
                intent = "evolution"
            elif any(term in text for term in ("下载", "运行构建", "命令", "tool")):
                intent = "tool"
            elif any(term in text for term in ("入口文件", "项目", "工作区", "workspace")):
                intent = "workspace"
            elif any(term in text for term in ("执行任务", "修复", "task", "fix")):
                intent = "task"
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": intent,
                        "confidence": 0.9,
                        "reason": "input/output test classifier",
                    },
                    ensure_ascii=False,
                ),
                finish_reason="stop",
                model=self.name,
            )
        return LLMResponse(content="ok", finish_reason="stop", model=self.name)


class ProjectAnalyzeIntentModel(InputOutputIntentModel):
    def __init__(self) -> None:
        self.saw_project_analyze_result = False

    async def chat(self, messages, *, tools=()):
        first = messages[0] if messages else None
        if (
            first is not None
            and first.role is Role.SYSTEM
            and first.content
            and "Classify the user's intent" in first.content
        ):
            return await super().chat(messages, tools=tools)
        self.saw_project_analyze_result = any(
            message.role is Role.TOOL and message.name == "project_analyze"
            for message in messages
        )
        return LLMResponse(content="project analyzed", finish_reason="stop", model=self.name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_text", "expected_intent", "expected_event"),
    INPUT_OUTPUT_CASES,
)
async def test_intent_recognition_input_output_cases(
    input_text: str,
    expected_intent: str,
    expected_event: str,
) -> None:
    runtime, _ = build_runtime(model=InputOutputIntentModel())
    seen: list[tuple[str, dict]] = []
    runtime.events.subscribe("*", lambda event: seen.append((event.name, dict(event.payload))))

    await runtime.handle(Message(input_text))

    intent_payload = next(payload for name, payload in seen if name == INTENT_RECOGNIZED)
    event_names = [name for name, _ in seen]
    print(f"input={input_text} output={intent_payload['intent']} event={expected_event}")
    assert intent_payload["intent"] == expected_intent
    assert intent_payload["trigger_event"] == expected_event
    assert expected_event in event_names


@pytest.mark.parametrize(
    "text",
    [
        "请扫描项目结构",
        "請掃描專案結構",
        "scan project structure",
        "プロジェクトを分析してください",
        "프로젝트 구조를 분석해줘",
        "проанализируй проект",
        "analizar proyecto",
        "analisar projeto",
    ],
)
def test_project_analyze_intent_builds_tool_call_for_supported_languages(text: str) -> None:
    call = _project_analyze_tool_call(
        Message(text, metadata={"workspace_path": "/tmp/project"}),
        "workspace",
    )

    assert call is not None
    assert call["name"] == "project_analyze"
    assert call["arguments"]["path"] == "/tmp/project"
    assert call["arguments"]["instruction"] == text


@pytest.mark.asyncio
async def test_workspace_intent_invokes_project_analyze_tool() -> None:
    model = ProjectAnalyzeIntentModel()
    runtime, _ = build_runtime(model=model)

    reply = await runtime.handle(Message("请扫描项目结构"))

    assert reply.content == "project analyzed"
    assert model.saw_project_analyze_result is True
    turns = await runtime.history(reply.session_id)
    metadata = turns[0].metadata["message_metadata"]
    assert metadata["intent"] == "workspace"
    assert metadata["resume_tool_calls"][0]["name"] == "project_analyze"


@pytest.mark.asyncio
async def test_intent_recognition_triggers_event_and_persists_metadata() -> None:
    runtime, _ = build_runtime(model=ScriptedModel([]))
    seen: list[tuple[str, dict]] = []
    runtime.events.subscribe("*", lambda event: seen.append((event.name, dict(event.payload))))

    reply = await runtime.handle(Message("请执行任务：修复测试"))

    names = [name for name, _ in seen]
    assert INTENT_RECOGNIZED in names
    assert INTENT_TASK_REQUESTED in names
    intent_payload = next(payload for name, payload in seen if name == INTENT_RECOGNIZED)
    assert intent_payload["intent"] == "task"
    assert intent_payload["trigger_event"] == INTENT_TASK_REQUESTED

    turns = await runtime.history(reply.session_id)
    assert turns[0].metadata["message_metadata"]["intent"] == "task"


@pytest.mark.asyncio
async def test_intent_prompt_includes_similar_context_from_vector_store() -> None:
    class RecordingContextStore:
        def __init__(self, record: ContextRecord) -> None:
            self.record = record

        async def append(self, record: ContextRecord) -> None:
            self.record = record

        async def latest(self, session_id: str) -> ContextRecord | None:
            return self.record if session_id == self.record.session_id else None

        async def list_records(self, session_id: str, *, limit: int = 20):
            return [self.record] if session_id == self.record.session_id else []

        async def search(self, query: str, *, limit: int = 10):
            return []

        async def count(self) -> int:
            return 1

    class CapturingModel:
        name = "capturing"

        def __init__(self) -> None:
            self.intent_prompt = ""

        async def chat(self, messages, *, tools=()):
            first = messages[0] if messages else None
            if (
                first is not None
                and first.role is Role.SYSTEM
                and first.content
                and "Classify the user's intent" in first.content
            ):
                self.intent_prompt = str(messages[-1].content or "")
                return LLMResponse(
                    content='{"intent":"task","confidence":0.91}',
                    finish_reason="stop",
                )
            return LLMResponse(content="ok", finish_reason="stop")

    storage = StorageBundle.in_memory()
    record = ContextRecord(
        session_id="prior-session",
        snapshot_hash="hash-similar",
        text="Previous context: deploy workflow failed after pytest.",
    )
    storage.context = RecordingContextStore(record)  # type: ignore[assignment]
    assert storage.vectors is not None
    await storage.vectors.upsert(
        "context:prior-session:hash-similar",
        HashingEmbedder()("deploy workflow failed after pytest"),
        namespace=CONTEXT_SNAPSHOTS_NS,
        metadata={"session_id": record.session_id, "hash": record.snapshot_hash},
    )
    model = CapturingModel()
    runtime, _ = build_runtime(storage=storage, model=model)

    await runtime.handle(Message("please analyze the deploy workflow"))

    assert "similar_context_from_vector_db" in model.intent_prompt
    assert "context_weight" in model.intent_prompt
    assert "detail_level" in model.intent_prompt
    assert "distilled_text" in model.intent_prompt
    assert "Previous context: deploy workflow failed after pytest." in model.intent_prompt

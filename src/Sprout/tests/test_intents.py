"""Tests for the consolidated intent table and hybrid task routing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from Sprout.config.loader import default_settings
from Sprout.events.catalog import INTENT_DELETE_REQUESTED, INTENT_TASK_REQUESTED
from Sprout.intents import (
    DEFAULT_INTENT,
    INTENT_EVENTS,
    Intent,
    LayaIntentRecognizer,
    detect_delete_hint,
    detect_task_hint,
    intent_event,
    laya_intent_state,
    normalize_intent,
)
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime
from Sprout.tests.conftest import TestIntentRecognizer


def test_detect_task_hint() -> None:
    assert detect_task_hint("/task fix the bug") is True
    assert detect_task_hint("修复一个 bug") is True
    assert detect_task_hint("帮我敲一个sample.py") is True
    assert detect_task_hint("敲个 sample_module.py") is True
    assert detect_task_hint("please refactor this module") is True
    assert detect_task_hint("删除 src/obsolete.py") is True
    assert detect_delete_hint("请删除 src/obsolete.py") is True
    assert detect_delete_hint("请删除这个文件") is True
    assert detect_delete_hint("如何删除这个文件？") is False
    assert detect_delete_hint("你可以删除这个文件吗？") is False
    assert detect_delete_hint("把旧演示脚本清理掉") is True
    assert detect_delete_hint("discard the old source module") is True
    assert detect_delete_hint("不要删除 src/keep.py") is False
    assert detect_task_hint("你好") is False
    assert detect_task_hint("介绍一下这个项目") is False


def test_intent_table_is_single_source() -> None:
    assert INTENT_EVENTS[Intent.TASK] == INTENT_TASK_REQUESTED
    assert intent_event("task") == INTENT_TASK_REQUESTED
    assert INTENT_EVENTS[Intent.DELETE] == INTENT_DELETE_REQUESTED
    assert intent_event("delete") == INTENT_DELETE_REQUESTED
    assert normalize_intent("task") is Intent.TASK
    assert normalize_intent("unknown") is DEFAULT_INTENT
    assert set(INTENT_EVENTS.values()) == {
        "intent.conversation.requested",
        "intent.task.requested",
        "intent.delete.requested",
        "intent.workspace.requested",
        "intent.tool.requested",
        "intent.approval.requested",
        "intent.memory.requested",
        "intent.evolution.requested",
        "intent.strategy.requested",
    }


def test_laya_intent_recognizer_uses_choice_question_and_decodes_answer() -> None:
    class Router:
        def __init__(self) -> None:
            self.calls = []

        def predict(self, state, questions, **kwargs):
            self.calls.append((state, questions, kwargs))
            return {
                "answers": {
                    "intent": {
                        "choice": "task",
                        "answer_confidence": 0.87,
                        "probabilities": {"task": 0.87, "conversation": 0.13},
                    }
                }
            }

    router = Router()
    recognizer = LayaIntentRecognizer(router_factory=lambda: router)

    result = recognizer.classify(laya_intent_state(message="fix tests"))

    assert result["intent"] == "task"
    assert result["trigger_event"] == INTENT_TASK_REQUESTED
    assert result["confidence"] == 0.87
    assert result["reason"] == "laya_router"
    assert result["intent_probabilities"]["task"] == 0.87
    state, questions, kwargs = router.calls[0]
    assert state["message"] == "fix tests"
    assert questions["intent"]["type"] == "choice"
    assert "task" in questions["intent"]["criteria"]
    assert kwargs["task"] == "intent"


def test_laya_intent_recognizer_default_router_cache_uses_router_instance(
    monkeypatch,
) -> None:
    class Router:
        def __init__(self, *, preload: bool) -> None:
            self.preload = preload

        def predict(self, state, questions, **kwargs):
            return {
                "answers": {
                    "intent": {
                        "choice": "conversation",
                        "answer_confidence": 0.79,
                    }
                }
            }

    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(Router=Router))
    monkeypatch.setattr(LayaIntentRecognizer, "_router_instance", None)

    result = LayaIntentRecognizer().classify(laya_intent_state(message="hello"))

    assert result["intent"] == "conversation"
    assert result["confidence"] == 0.79
    assert LayaIntentRecognizer._router_instance is not None
    assert LayaIntentRecognizer._router_instance.preload is False


def test_task_intent_submits_async(tmp_path: Path) -> None:
    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'metadata.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "trajectory")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "security.jsonl")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(settings)
        runtime._intent_recognizer = TestIntentRecognizer()  # noqa: SLF001
        workspace = await runtime.open_workspace(tmp_path)
        reply = await runtime.handle(
            Message("帮我敲一个sample.py", metadata={"workspace_id": workspace.id})
        )
        assert "任务已提交" in reply.content
        assert (reply.metadata or {}).get("intent") == "task"
        assert (reply.metadata or {}).get("task_id")
        await runtime.stop()

    asyncio.run(run())


def test_delete_intent_creates_a_delete_task(tmp_path: Path) -> None:
    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'metadata.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "trajectory")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "security.jsonl")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )

    async def run() -> None:
        runtime = create_runtime(settings)
        runtime._intent_recognizer = TestIntentRecognizer()  # noqa: SLF001
        queued = []

        async def capture(task) -> None:
            queued.append(task)

        runtime.submit_task = capture
        runtime.start_worker = lambda: None
        reply = await runtime.handle(
            Message("请删除 src/obsolete.py")
        )

        assert (reply.metadata or {}).get("intent") == "delete"
        assert "是否以" in reply.content
        resumed = await runtime.grant_workspace_consent(
            reply.session_id, root=tmp_path
        )
        assert (resumed.metadata or {}).get("intent") == "delete"
        assert len(queued) == 1
        assert queued[0].metadata["operation"] == "delete"
        await runtime.stop()

    asyncio.run(run())

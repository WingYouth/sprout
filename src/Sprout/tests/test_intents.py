"""Tests for the consolidated intent table and hybrid task routing."""

from __future__ import annotations

import asyncio
from pathlib import Path

from Sprout.config.loader import default_settings
from Sprout.events.catalog import INTENT_TASK_REQUESTED
from Sprout.intents import (
    DEFAULT_INTENT,
    INTENT_EVENTS,
    Intent,
    detect_task_hint,
    intent_event,
    normalize_intent,
)
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime


def test_detect_task_hint() -> None:
    assert detect_task_hint("/task fix the bug") is True
    assert detect_task_hint("修复一个 bug") is True
    assert detect_task_hint("please refactor this module") is True
    assert detect_task_hint("你好") is False
    assert detect_task_hint("介绍一下这个项目") is False


def test_intent_table_is_single_source() -> None:
    assert INTENT_EVENTS[Intent.TASK] == INTENT_TASK_REQUESTED
    assert intent_event("task") == INTENT_TASK_REQUESTED
    assert normalize_intent("task") is Intent.TASK
    assert normalize_intent("unknown") is DEFAULT_INTENT
    assert set(INTENT_EVENTS.values()) == {
        "intent.conversation.requested",
        "intent.task.requested",
        "intent.workspace.requested",
        "intent.tool.requested",
        "intent.approval.requested",
        "intent.memory.requested",
        "intent.evolution.requested",
    }


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
        workspace = await runtime.open_workspace(tmp_path)
        reply = await runtime.handle(
            Message("修复一个 bug", metadata={"workspace_id": workspace.id})
        )
        assert "任务已提交" in reply.content
        assert (reply.metadata or {}).get("intent") == "task"
        assert (reply.metadata or {}).get("task_id")
        await runtime.stop()

    asyncio.run(run())

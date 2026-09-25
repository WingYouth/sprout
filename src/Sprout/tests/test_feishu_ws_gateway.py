"""Feishu WebSocket gateway approval loop: decision polling and final replies."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from Sprout.gateway.channels.feishu_ws import FeishuWebSocketGateway
from Sprout.task.models import Task, TaskResult, TaskStatus


def _gateway(runtime=None, reply_client=None) -> FeishuWebSocketGateway:
    gateway = object.__new__(FeishuWebSocketGateway)
    gateway._runtime = runtime
    gateway._reply_client = reply_client
    return gateway


async def test_task_reply_completed_with_content() -> None:
    gateway = _gateway()
    result = TaskResult(task_id="t", status=TaskStatus.COMPLETED, content="hello")
    assert await gateway._task_reply("t", result) == "hello"


async def test_task_reply_failed() -> None:
    gateway = _gateway()
    result = TaskResult(task_id="t", status=TaskStatus.FAILED, error="boom")
    assert await gateway._task_reply("t", result) == "任务失败：boom"


async def test_task_reply_completed_falls_back_to_agent_content() -> None:
    class FakeMetadata:
        async def list_execution_nodes(self, task_id):
            return [
                SimpleNamespace(
                    type=SimpleNamespace(value="agent"),
                    metadata={"output": {"content": "This project is Python"}},
                )
            ]

    class FakeRuntime:
        storage = SimpleNamespace(metadata=FakeMetadata())

    gateway = _gateway(runtime=FakeRuntime())
    result = TaskResult(task_id="t", status=TaskStatus.COMPLETED, content="")
    assert await gateway._task_reply("t", result) == "This project is Python"


async def test_wait_for_decision_resumes_on_approval(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    task = Task(id="t1", status=TaskStatus.WAITING_APPROVAL)
    pending = SimpleNamespace(status=SimpleNamespace(value="pending"))
    approved = SimpleNamespace(status=SimpleNamespace(value="approved"))
    calls: list[list] = [[pending], [approved]]

    class FakeRuntime:
        async def get_task(self, _task_id):
            return task

        async def list_change_proposals(self, _task_id):
            return calls.pop(0)

        async def resume_task(self, _task):
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                content="resumed",
            )

    gateway = _gateway(runtime=FakeRuntime())
    result = await gateway._wait_for_decision("t1", "ou_x", "open_id")

    assert result is not None
    assert result.status is TaskStatus.COMPLETED
    assert result.content == "resumed"


async def test_wait_for_decision_replies_on_rejection(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    task = Task(id="t1", status=TaskStatus.WAITING_APPROVAL)
    rejected = SimpleNamespace(status=SimpleNamespace(value="rejected"))

    class FakeRuntime:
        async def get_task(self, _task_id):
            return task

        async def list_change_proposals(self, _task_id):
            return [rejected]

    sent: list[str] = []

    class FakeReplyClient:
        async def send_text(self, receive_id, text, *, receive_id_type):
            sent.append(text)

    gateway = _gateway(runtime=FakeRuntime(), reply_client=FakeReplyClient())
    result = await gateway._wait_for_decision("t1", "ou_x", "open_id")

    assert result is None
    assert sent == ["任务已被拒绝"]

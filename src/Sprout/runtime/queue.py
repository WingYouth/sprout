"""Temporal-backed task queue used by the runtime."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Protocol

from Sprout.task.models import Task


class TaskQueueBackend(Protocol):
    async def put(self, task: Task) -> None: ...
    async def get(self) -> Task: ...
    def task_done(self) -> None: ...
    def qsize(self) -> int: ...
    def empty(self) -> bool: ...
    def __aiter__(self) -> AsyncIterator[Task]: ...


class TaskQueue(TaskQueueBackend):
    """FIFO queue for tasks before workspace execution."""

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=maxsize)

    async def put(self, task: Task) -> None:
        await self._queue.put(task)

    async def get(self) -> Task:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def __aiter__(self) -> AsyncIterator[Task]:
        while True:
            task = await self.get()
            yield task


class TemporalTaskQueue(TaskQueue):
    """Queue that submits every task to Temporal for durable orchestration."""

    def __init__(self) -> None:
        super().__init__()
        self._host = os.getenv("TEMPORAL_HOST", "127.0.0.1:7233")

    async def put(self, task: Task) -> None:
        await super().put(task)
        from temporalio.client import Client

        client = await Client.connect(
            self._host,
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
        )
        await client.start_workflow(
            "SproutTaskWorkflow",
            task,
            id=f"sprout-task-{task.id}",
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "sprout-tasks"),
        )


def create_task_queue() -> TaskQueueBackend:
    """Return the configured task-queue backend.

    Temporal is the durable production queue, but it is opt-in via
    ``TEMPORAL_HOST``; the offline/local default is a plain in-process FIFO so
    task submission never blocks waiting for a Temporal worker.
    """
    if os.getenv("TEMPORAL_HOST"):
        return TemporalTaskQueue()
    return TaskQueue()

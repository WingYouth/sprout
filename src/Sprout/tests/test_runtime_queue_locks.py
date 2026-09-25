"""Tests for runtime task queue and workspace locks."""

from __future__ import annotations

import asyncio

from Sprout.config.loader import default_settings
from Sprout.runtime.factory import create_runtime
from Sprout.runtime.locks import WorkspaceLockManager
from Sprout.runtime.queue import TaskQueue
from Sprout.task.models import Task


def test_task_queue_is_fifo() -> None:
    queue = TaskQueue()
    first = Task(workspace_id="ws-1", instruction="first")
    second = Task(workspace_id="ws-1", instruction="second")

    async def run() -> None:
        await queue.put(first)
        await queue.put(second)
        assert await queue.get() is first
        assert await queue.get() is second
        queue.task_done()
        queue.task_done()

    asyncio.run(run())


def test_workspace_lock_manager_serializes_same_workspace() -> None:
    manager = WorkspaceLockManager()
    active = 0
    max_active = 0

    async def run_task() -> None:
        nonlocal active, max_active
        async with manager.lock("ws-1"):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            active -= 1

    async def run() -> None:
        await asyncio.gather(run_task(), run_task())
        assert max_active == 1

    asyncio.run(run())


def test_runtime_worker_processes_queued_tasks(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'metadata.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "trajectory")
    settings.storage.blobs_dir = str(tmp_path / "blobs")

    async def run() -> None:
        runtime = create_runtime(settings, task_queue=TaskQueue())
        workspace = await runtime.open_workspace(tmp_path)
        task = await runtime.create_task(workspace.id, "explain this project")
        runtime.start_worker()
        await runtime.submit_task(task)
        await asyncio.sleep(0.2)
        await runtime.stop_worker()
        await runtime.stop()

    asyncio.run(run())

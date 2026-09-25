"""Async interval scheduler for background jobs (evolution runs, cleanup, ...)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from Sprout.scheduler.task import ScheduledJob

logger = logging.getLogger("sprout.scheduler")


class Scheduler:
    """Runs registered callbacks on fixed intervals; failures never stop the loop."""

    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}

    def every(
        self, name: str, interval_seconds: float, callback: Callable[[], Awaitable[None]]
    ) -> ScheduledJob:
        job = ScheduledJob(name=name, interval_seconds=interval_seconds, callback=callback)
        self._jobs[name] = job
        return job

    def remove(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is not None and job._task is not None:
            job._task.cancel()

    def job(self, name: str) -> ScheduledJob | None:
        return self._jobs.get(name)

    def jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())

    async def run_pending(self) -> int:
        """Run every due job once; returns the number of jobs executed."""
        executed = 0
        for job in list(self._jobs.values()):
            if not job.is_due:
                continue
            executed += 1
            await self._run(job)
        return executed

    def start(self) -> None:
        """Start the background loop task (idempotent)."""
        for job in self._jobs.values():
            if job._task is None or job._task.done():
                job._task = asyncio.create_task(
                    self._loop(job), name=f"sprout-scheduler-{job.name}"
                )

    async def stop(self) -> None:
        for job in self._jobs.values():
            if job._task is not None:
                job._task.cancel()
                job._task = None

    async def _loop(self, job: ScheduledJob) -> None:
        try:
            while job.enabled:
                await asyncio.sleep(job.interval_seconds)
                await self._run(job)
        except asyncio.CancelledError:
            raise

    @staticmethod
    async def _run(job: ScheduledJob) -> None:
        try:
            await job.callback()
            job.last_error = None
        except Exception as exc:  # noqa: BLE001 - background jobs must not crash the loop
            job.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Scheduled job %s failed: %s", job.name, job.last_error)
        finally:
            from datetime import UTC, datetime

            job.run_count += 1
            job.last_run_at = datetime.now(UTC)
            job.next_run_at = job.last_run_at  # next due after one interval
            job.next_run_at = datetime.now(UTC)

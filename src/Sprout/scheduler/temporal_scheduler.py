"""Temporal Schedule adapter for background jobs."""

from __future__ import annotations

import os
from typing import Any


class TemporalScheduler:
    def __init__(
        self,
        *,
        host: str | None = None,
        namespace: str | None = None,
        task_queue: str | None = None,
    ) -> None:
        self.host = host or os.getenv("TEMPORAL_HOST", "127.0.0.1:7233")
        self.namespace = namespace or os.getenv("TEMPORAL_NAMESPACE", "default")
        self.task_queue = task_queue or os.getenv(
            "TEMPORAL_TASK_QUEUE", "sprout-tasks"
        )

    async def create_schedule(
        self,
        *,
        schedule_id: str,
        workflow: str,
        args: Any,
        interval_seconds: float,
        overlap: str = "SKIP",
    ) -> None:
        from temporalio.client import (
            Client,
            Schedule,
            ScheduleActionStartWorkflow,
            ScheduleIntervalSpec,
            ScheduleOverlapPolicy,
            ScheduleSpec,
        )

        client = await Client.connect(self.host, namespace=self.namespace)
        await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow,
                    args,
                    id=f"sprout-schedule-{schedule_id}",
                    task_queue=self.task_queue,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=interval_seconds)]
                ),
                policy=None,
                overlap_policy=ScheduleOverlapPolicy[overlap],
            ),
        )

"""Scheduler job model (in-memory; persisted tasks live in the operational store)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    callback: Callable[[], Awaitable[None]]
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
    run_count: int = 0
    _task: asyncio.Task[Any] | None = field(default=None, repr=False, compare=False)

    @property
    def is_due(self) -> bool:
        return self.enabled and datetime.now(UTC) >= self.next_run_at

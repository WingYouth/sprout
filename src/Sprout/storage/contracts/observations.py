"""Observation store contract: raw events and reflections.

This is the data behind ``sprout_audit.db`` in the local-first layout.
Trajectories are derived from events via ``correlation_id`` instead of being
stored separately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from Sprout.events.event import Event


@dataclass(frozen=True, slots=True)
class ReflectionRecord:
    """A stored summary produced by the reflection stage of the growth layer."""

    summary: str
    stats: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ObservationStore(Protocol):
    async def append_event(self, event: Event) -> None: ...
    async def list_events(self, limit: int = 100) -> Sequence[Event]: ...
    async def count_events(self) -> int: ...

    async def append_reflection(self, reflection: ReflectionRecord) -> None: ...
    async def list_reflections(self, limit: int = 50) -> Sequence[ReflectionRecord]: ...

"""In-memory observation store."""

from __future__ import annotations

from Sprout.events.event import Event
from Sprout.storage.contracts.observations import ReflectionRecord


class MemoryObservationStore:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.reflections: list[ReflectionRecord] = []

    async def append_event(self, event: Event) -> None:
        self.events.append(event)

    async def list_events(self, limit: int = 100) -> list[Event]:
        return self.events[-limit:]

    async def count_events(self) -> int:
        return len(self.events)

    async def append_reflection(self, reflection: ReflectionRecord) -> None:
        self.reflections.append(reflection)

    async def list_reflections(self, limit: int = 50) -> list[ReflectionRecord]:
        return self.reflections[-limit:]

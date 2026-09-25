"""In-process event bus isolated from the online request path."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable

from Sprout.events.catalog import EVENT_LANES, RUNTIME_STARTED
from Sprout.events.event import Event

EventHandler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """Fan-out bus. Handler failures never break the online request path."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._known_events: dict[str, str] = {}

    def subscribe(self, name: str, handler: EventHandler) -> None:
        """Subscribe to one event name, or ``"*"`` to receive every event."""
        self._handlers[name].append(handler)

    def register_event(self, name: str, lane: str = "audit") -> None:
        """Declare an event and the authority lane it should route to."""
        if not name:
            raise ValueError("event name cannot be empty")
        self._known_events[name] = lane

    def register_events(self, routes: dict[str, str]) -> None:
        """Register many ``{event_name: lane}`` routes at once."""
        for name, lane in routes.items():
            self.register_event(name, lane)

    def lane_for(self, name: str) -> str:
        """Return the registered lane for ``name``, or the ``audit`` default."""
        return self._known_events.get(name, "audit")

    def known_events(self) -> dict[str, str]:
        """Snapshot the registered event -> lane table."""
        return dict(self._known_events)

    def unsubscribe(self, name: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(name, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        handlers = [*self._handlers.get(event.name, ()), *self._handlers.get("*", ())]
        if not handlers:
            return
        await asyncio.gather(
            *(self._invoke(handler, event) for handler in handlers), return_exceptions=True
        )

    async def publish_simple(self, name: str, payload: dict | None = None) -> None:
        """Convenience helper mirroring ``Event(name, payload)`` publishing."""
        await self.publish(Event(name, payload or {}))

    @staticmethod
    async def _invoke(handler: EventHandler, event: Event) -> None:
        result = handler(event)
        if inspect.isawaitable(result):
            await result


def register_builtin_events(bus: EventBus) -> EventBus:
    """Register every canonical event name with its default authority lane."""
    bus.register_events(EVENT_LANES)
    return bus


__all__ = [
    "EVENT_LANES",
    "RUNTIME_STARTED",
    "Event",
    "EventBus",
    "EventHandler",
    "register_builtin_events",
]

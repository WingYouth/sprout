"""Persist every bus event to the observations lane. Fail-open, log-only.

The recorder is the bridge between the in-process :class:`~Sprout.events.bus.EventBus`
and the :class:`~Sprout.storage.contracts.observations.ObservationStore`
(sprout_audit.db). It subscribes to ``"*"`` so the whole message lifecycle —
``message.received`` → ``agent.started`` → ``agent.completed``/``agent.failed``
→ ``message.persisted`` → ``message.sent`` — lands in the events table.

Two safety properties, both load-bearing:

1. **Fail-open.** An observations-lane failure (disk full, locked SQLite,
   schema drift) is logged and swallowed: the online request path must never
   go down because a derived lane did. Derived data is rebuildable.
2. **Log-only, never re-publish.** Publishing an ``audit.write_failed`` event
   from inside the recorder would re-enter the bus, hit the recorder again,
   fail again, and recurse forever. The error is logged with ``logger.error``
   and that is the entire remediation surface.
"""

from __future__ import annotations

import logging
from typing import Any

from Sprout.events.event import Event

logger = logging.getLogger("Sprout.events.recorder")

#: Maximum characters kept for any single string value in an event payload.
#: Long bodies (file contents, tool outputs) would bloat the events table;
#: the full bodies live in the session/blob lanes, not here.
MAX_PAYLOAD_CHARS = 4096

_TRUNCATION_SUFFIX = "…[truncated]"


def clamp_payload(
    value: Any, max_chars: int = MAX_PAYLOAD_CHARS
) -> Any:
    """Recursively shorten over-long strings inside an event payload."""
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + _TRUNCATION_SUFFIX
    if isinstance(value, dict):
        return {key: clamp_payload(item, max_chars) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        clamped = [clamp_payload(item, max_chars) for item in value]
        return type(value)(clamped) if isinstance(value, tuple) else clamped
    return value


class ObservationRecorder:
    """EventBus handler that appends every event to the observation store."""

    def __init__(self, store: Any, *, max_payload_chars: int = MAX_PAYLOAD_CHARS) -> None:
        self._store = store
        self._max_chars = max_payload_chars

    async def __call__(self, event: Event) -> None:
        try:
            payload = clamp_payload(dict(event.payload), self._max_chars)
            await self._store.append_event(
                Event(
                    name=event.name,
                    payload=payload,
                    correlation_id=event.correlation_id,
                    id=event.id,
                    occurred_at=event.occurred_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 - fail-open, and log-only:
            # re-publishing an audit event here would re-enter the bus and
            # recurse; the log line is the complete failure record.
            logger.error(
                "observations lane dropped event %s (%s): %s: %s",
                event.name,
                event.id,
                type(exc).__name__,
                exc,
            )


__all__ = ["MAX_PAYLOAD_CHARS", "ObservationRecorder", "clamp_payload"]

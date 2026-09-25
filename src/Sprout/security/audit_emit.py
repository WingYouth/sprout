"""Bridge synchronous audit-write failures onto the async event bus (AUTHZ §7.4).

:class:`~Sprout.security.audit.SecurityAuditLog` is synchronous by design: it
degrades inside the caller's request path and must never ``await``. The hook
built here is installed on the log by :class:`~Sprout.security.layer.SecurityLayer`
so a degraded write is *also* observable as the ``audit.write_failed`` event.

Fail-open in both directions:

* no running loop (a CLI/one-shot caller) — the hook returns without scheduling;
  the log has already written stderr and the ``.fallback`` sidecar.
* a bus that is absent or has no subscribers — ``EventBus.publish`` is a no-op.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from Sprout.events import AUDIT_WRITE_FAILED, Event, EventBus

#: Signature of the synchronous hook installed on ``SecurityAuditLog.on_failure``.
AuditFailureHook = Callable[[str, str, Mapping[str, Any]], None]


def make_audit_failure_hook(events: EventBus) -> AuditFailureHook:
    """Return a sync hook that schedules ``audit.write_failed`` on the live loop."""

    def _hook(error: str, kind: str, payload: Mapping[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop -> nothing to publish on; already degraded
            return
        loop.create_task(
            events.publish(
                Event(
                    AUDIT_WRITE_FAILED,
                    {"error": error, "kind": kind, **dict(payload)},
                )
            )
        )

    return _hook


__all__ = ["AuditFailureHook", "make_audit_failure_hook"]

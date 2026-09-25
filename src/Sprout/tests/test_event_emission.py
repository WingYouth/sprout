"""Event-emission coverage for the four authorization constants (EVT-01).

``POLICY_DECIDED``, ``AUTH_SCOPE_EXPIRED``, ``AUTH_ROLES_DISCARDED`` and
``AUDIT_WRITE_FAILED`` are declared in ``EVENT_LANES``, which only routes them.
This module is the structural guard that each one is actually *emitted* from a
live code path — a constant with a lane but no emitter is a dead constant, and
that was defect EVT-01.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from Sprout.events.bus import EventBus
from Sprout.events.types import (
    AUDIT_WRITE_FAILED,
    AUTH_ROLES_DISCARDED,
    AUTH_SCOPE_EXPIRED,
    POLICY_DECIDED,
)
from Sprout.execution.file_broker import FileBroker
from Sprout.execution.models import SandboxRef
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.message.models import Message
from Sprout.security.audit import SecurityAuditLog
from Sprout.security.audit_emit import make_audit_failure_hook
from Sprout.security.engine import PolicyEngine
from Sprout.task.models import DelegationScope


def _recording_bus() -> tuple[EventBus, list[str]]:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("*", lambda event: seen.append(event.name))
    return bus, seen


# -- policy.decided -----------------------------------------------------------


async def test_file_broker_emits_policy_decided(tmp_path: Path) -> None:
    """A write that reaches the policy engine is observable on the bus."""
    bus, seen = _recording_bus()
    sandbox = SandboxRef(id="sb-1", kind="git_worktree", root=tmp_path)
    broker = FileBroker(PolicyEngine(), events=bus)

    await broker.write_text(sandbox, "src/app.py", "print('hi')\n")

    assert POLICY_DECIDED in seen


async def test_broker_without_a_bus_still_decides(tmp_path: Path) -> None:
    """``events`` is optional: the decision path must not require a bus."""
    sandbox = SandboxRef(id="sb-2", kind="git_worktree", root=tmp_path)
    broker = FileBroker(PolicyEngine())

    result = await broker.write_text(sandbox, "src/app.py", "print('hi')\n")

    assert result.wrote


# -- auth.scope_expired -------------------------------------------------------


async def test_an_expired_scope_emits_auth_scope_expired(tmp_path: Path) -> None:
    bus, seen = _recording_bus()
    sandbox = SandboxRef(id="sb-3", kind="git_worktree", root=tmp_path)
    broker = FileBroker(PolicyEngine(), events=bus)
    expired = DelegationScope(expires_at=datetime.now(UTC) - timedelta(seconds=1))

    result = await broker.write_text(sandbox, "src/app.py", "x", scope=expired)

    assert not result.wrote
    assert AUTH_SCOPE_EXPIRED in seen


async def test_a_live_scope_does_not_emit_scope_expired(tmp_path: Path) -> None:
    bus, seen = _recording_bus()
    sandbox = SandboxRef(id="sb-4", kind="git_worktree", root=tmp_path)
    broker = FileBroker(PolicyEngine(), events=bus)
    live = DelegationScope(expires_at=datetime.now(UTC) + timedelta(hours=1))

    await broker.write_text(sandbox, "src/app.py", "x", scope=live)

    assert AUTH_SCOPE_EXPIRED not in seen


# -- auth.roles_discarded -----------------------------------------------------


class _StubRuntime:
    """Minimal duck-typed Runtime: the gateway only needs ``events``/``execute``."""

    def __init__(self, events: EventBus) -> None:
        self.events = events

    async def execute(self, task: object) -> SimpleNamespace:
        return SimpleNamespace(
            task_id=getattr(task, "id", "task-1"),
            status=SimpleNamespace(value="completed"),
            content="ok",
            metrics={},
        )


async def test_gateway_emits_roles_discarded() -> None:
    bus, seen = _recording_bus()
    gateway = RuntimeGateway(_StubRuntime(bus))  # type: ignore[arg-type]
    message = Message(
        content="hi",
        channel="web",
        user_id="u1",
        metadata={"workspace_id": "ws-1", "roles": ["admin"]},
    )

    await gateway.execute_message(message)

    assert AUTH_ROLES_DISCARDED in seen


async def test_gateway_stays_quiet_without_declared_roles() -> None:
    bus, seen = _recording_bus()
    gateway = RuntimeGateway(_StubRuntime(bus))  # type: ignore[arg-type]
    message = Message(
        content="hi",
        channel="web",
        user_id="u1",
        metadata={"workspace_id": "ws-1"},
    )

    await gateway.execute_message(message)

    assert AUTH_ROLES_DISCARDED not in seen


# -- audit.write_failed -------------------------------------------------------


async def test_a_degraded_audit_write_publishes_audit_write_failed(tmp_path: Path) -> None:
    """The synchronous log schedules the event on the running loop."""
    bus, seen = _recording_bus()
    # A directory where a file is expected makes ``_append`` fail deterministically.
    log = SecurityAuditLog(tmp_path)
    log.on_failure = make_audit_failure_hook(bus)

    log.record("policy.decided", {"path": "src/app.py"})
    await asyncio.sleep(0.01)  # let the scheduled publish task run to completion

    assert log.failures == 1
    assert AUDIT_WRITE_FAILED in seen


async def test_the_audit_hook_is_fail_open_without_a_loop(tmp_path: Path) -> None:
    """Called outside any event loop the hook must simply no-op."""
    bus, seen = _recording_bus()
    log = SecurityAuditLog(tmp_path)
    log.on_failure = make_audit_failure_hook(bus)

    # ``record`` is synchronous; here it runs in a thread with no running loop.
    await asyncio.to_thread(log.record, "policy.decided", {"path": "src/app.py"})

    assert log.failures == 1
    assert AUDIT_WRITE_FAILED not in seen

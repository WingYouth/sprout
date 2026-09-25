"""Operational store contract: sessions, turns, tasks, and approvals.

This is the Sprout approvals/audit authority behind ``sprout_audit.db`` in the
local-first layout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from Sprout.security.approval import ApprovalRecord, ApprovalStatus
from Sprout.session.models import Session, Turn


@dataclass(slots=True)
class Task:
    """A scheduled or deferred unit of work tracked by the runtime."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class OperationalStore(Protocol):
    # Sessions and turns
    async def get_session(self, session_id: str) -> Session | None: ...
    async def save_session(self, session: Session) -> None: ...
    async def append_turn(self, turn: Turn) -> None: ...
    async def recent_turns(self, session_id: str, limit: int = 20) -> Sequence[Turn]: ...
    async def count_sessions(self) -> int: ...
    async def count_turns(self) -> int: ...

    # Approvals (satisfies Sprout.security.approval.ApprovalStore)
    async def save_approval(self, record: ApprovalRecord) -> None: ...
    async def save_approval_if_status(
        self, record: ApprovalRecord, expected: ApprovalStatus
    ) -> bool: ...
    async def get_approval(self, approval_id: str) -> ApprovalRecord | None: ...
    async def list_approvals(
        self, status: ApprovalStatus | None = None
    ) -> Sequence[ApprovalRecord]: ...
    async def find_approval(
        self,
        tool: str,
        arguments_fingerprint: str,
        status: ApprovalStatus,
        task_id: str = "",
    ) -> ApprovalRecord | None: ...
    async def find_reusable_approval(
        self,
        tool: str,
        approval_class: str,
        status: ApprovalStatus,
        *,
        session_id: str,
        requested_by: str,
        source: str,
        task_id: str = "",
        resource_scope: str = "",
    ) -> ApprovalRecord | None: ...

    # Tasks
    async def save_task(self, task: Task) -> None: ...
    async def get_task(self, task_id: str) -> Task | None: ...
    async def list_tasks(self, status: str | None = None) -> Sequence[Task]: ...

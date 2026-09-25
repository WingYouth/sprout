"""In-memory operational store for tests and ephemeral runtimes."""

from __future__ import annotations

from dataclasses import replace

from Sprout.security.approval import ApprovalRecord, ApprovalStatus
from Sprout.session.models import Session, Turn
from Sprout.storage.contracts.operational import Task


class MemoryOperationalStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.turns: list[Turn] = []
        self.approvals: dict[str, ApprovalRecord] = {}
        self.tasks: dict[str, Task] = {}

    # Sessions and turns
    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def save_session(self, session: Session) -> None:
        self.sessions[session.id] = session

    async def append_turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        return [turn for turn in self.turns if turn.session_id == session_id][-limit:]

    async def count_sessions(self) -> int:
        return len(self.sessions)

    async def count_turns(self) -> int:
        return len(self.turns)

    # Approvals
    async def save_approval(self, record: ApprovalRecord) -> None:
        self.approvals[record.id] = replace(record)

    async def save_approval_if_status(
        self, record: ApprovalRecord, expected: ApprovalStatus
    ) -> bool:
        current = self.approvals.get(record.id)
        if current is None or current.status is not expected:
            return False
        self.approvals[record.id] = replace(record)
        return True

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        record = self.approvals.get(approval_id)
        return replace(record) if record is not None else None

    async def list_approvals(
        self, status: ApprovalStatus | None = None
    ) -> list[ApprovalRecord]:
        return [
            replace(record)
            for record in self.approvals.values()
            if status is None or record.status is status
        ]

    async def find_approval(
        self,
        tool: str,
        arguments_fingerprint: str,
        status: ApprovalStatus,
        task_id: str = "",
        class_key: str = "",
    ) -> ApprovalRecord | None:
        exact = None
        for record in self.approvals.values():
            if (
                record.tool == tool
                and record.arguments_fingerprint == arguments_fingerprint
                and record.status is status
                and record.task_id == task_id
            ):
                exact = replace(record)
                break
        if exact is not None:
            return exact
        return await self.find_class_approval(tool, class_key, status, task_id)

    async def find_class_approval(
        self,
        tool: str,
        class_key: str,
        status: ApprovalStatus,
        task_id: str = "",
    ) -> ApprovalRecord | None:
        """A reusable grant covering a whole command name, not one invocation."""
        if not class_key:
            return None
        for record in self.approvals.values():
            if (
                record.tool == tool
                and record.class_key == class_key
                and not record.single_use
                and record.status is status
                and record.task_id == task_id
            ):
                return replace(record)
        return None

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
    ) -> ApprovalRecord | None:
        for record in self.approvals.values():
            same_boundary = (
                record.session_id == session_id
                if session_id
                else record.task_id == task_id
            )
            if (
                record.tool == tool
                and record.approval_class == approval_class
                and record.status is status
                and not record.single_use
                and same_boundary
                and record.requested_by == requested_by
                and record.source == source
                and record.resource_scope == resource_scope
            ):
                return replace(record)
        return None

    # Tasks
    async def save_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    async def get_task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    async def list_tasks(self, status: str | None = None) -> list[Task]:
        return [task for task in self.tasks.values() if status is None or task.status == status]

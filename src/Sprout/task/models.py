"""Task domain model.

A task is the runtime's primary scheduling unit. Message-based entry points
must adapt into this model before execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from Sprout.gateway.identity import Principal


class TaskStatus(StrEnum):
    CREATED = "created"
    DISCOVERING = "discovering"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_RESOURCE = "waiting_resource"
    RETRYING = "retrying"
    PAUSED = "paused"
    EVALUATING = "evaluating"
    READY_TO_APPLY = "ready_to_apply"
    APPLYING = "applying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class Phase(StrEnum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    APPLY = "apply"


class TaskSource(StrEnum):
    """Where a task came from; drives approval grading (AUTHZ §5.3)."""

    INTERACTIVE = "interactive"
    CLI = "cli"
    CRON = "cron"
    AUTOMATION = "automation"
    MCP_CLIENT = "mcp_client"
    SYSTEM = "system"
    UNKNOWN = "unknown"


#: Sources with nobody watching: approvals default to deny for these.
UNATTENDED_SOURCES = frozenset({TaskSource.CRON, TaskSource.AUTOMATION})


def coerce_source(value: str | TaskSource | None) -> TaskSource:
    """Best-effort mapping of a free-form ``Task.source`` onto :class:`TaskSource`."""
    if isinstance(value, TaskSource):
        return value
    raw = (value or "").strip().casefold()
    if not raw:
        return TaskSource.UNKNOWN
    aliases = {
        "chat": TaskSource.INTERACTIVE,
        "interactive": TaskSource.INTERACTIVE,
        "web": TaskSource.INTERACTIVE,
        "cli": TaskSource.CLI,
        "cron": TaskSource.CRON,
        "schedule": TaskSource.CRON,
        "scheduled": TaskSource.CRON,
        "automation": TaskSource.AUTOMATION,
        "cron_job": TaskSource.AUTOMATION,
        "mcp": TaskSource.MCP_CLIENT,
        "mcp_client": TaskSource.MCP_CLIENT,
        "system": TaskSource.SYSTEM,
    }
    if raw in aliases:
        return aliases[raw]
    try:
        return TaskSource(raw)
    except ValueError:
        return TaskSource.UNKNOWN


@dataclass(frozen=True, slots=True)
class DelegationScope:
    """Intersection point for caller-granted permissions (AUTHZ §2.2).

    Empty ``allowed_*`` collections mean "unrestricted"; the ``denied_*`` sets
    always win. A scope may expire (``expires_at``) and may carry a delegation
    depth budget (``max_depth = 0`` means it cannot be delegated further). Child
    scopes are built with :meth:`narrow`, which can only tighten.
    """

    allowed_actions: frozenset[str] = frozenset()
    denied_actions: frozenset[str] = frozenset()
    allowed_paths: tuple[str, ...] = ()
    denied_paths: tuple[str, ...] = ()
    expires_at: datetime | None = None
    max_depth: int = 0
    issued_by: str = ""

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(UTC)) >= self.expires_at

    def permits(self, action: str, path: str = "", *, now: datetime | None = None) -> bool:
        if self.is_expired(now):
            return False
        if action in self.denied_actions:
            return False
        if self.allowed_actions and action not in self.allowed_actions:
            return False
        if self.denied_paths and any(path.startswith(prefix) for prefix in self.denied_paths):
            return False
        if self.allowed_paths and not any(path.startswith(prefix) for prefix in self.allowed_paths):
            return False
        return True

    def can_delegate(self) -> bool:
        return self.max_depth > 0

    def narrow(self, other: DelegationScope, *, issued_by: str = "") -> DelegationScope:
        """Intersect two scopes; the result is never broader than either one.

        A path restriction can be unsatisfiable: ``allowed_paths=("/a",)`` and
        ``("/b",)`` permit no common path. That overlap cannot be written as an
        empty ``allowed_paths`` — empty already means "unrestricted" — so it is
        expressed as ``denied_paths=("",)``, the empty prefix that ``permits``
        matches against every path. Writing it the other way round would have
        silently turned "these two grants exclude each other" into "no limit at
        all".
        """
        both_restrict_paths = bool(self.allowed_paths and other.allowed_paths)
        allowed_paths = _intersect_prefixes(self.allowed_paths, other.allowed_paths)
        denied_paths = tuple({*self.denied_paths, *other.denied_paths})
        if both_restrict_paths and not allowed_paths:
            # No shared subtree: deny everything rather than drop the limit.
            denied_paths = (*denied_paths, "")
        return DelegationScope(
            allowed_actions=_intersect_allowed(self.allowed_actions, other.allowed_actions),
            denied_actions=self.denied_actions | other.denied_actions,
            allowed_paths=allowed_paths,
            denied_paths=denied_paths,
            expires_at=_earliest(self.expires_at, other.expires_at),
            max_depth=_clamp_depth(self.max_depth, other.max_depth),
            issued_by=issued_by or other.issued_by or self.issued_by,
        )


def _intersect_allowed(
    left: frozenset[str], right: frozenset[str]
) -> frozenset[str]:
    if not left:
        return right
    if not right:
        return left
    return left & right


def _intersect_prefixes(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """The prefixes allowing what *both* sides allow.

    ``permits`` accepts a path when it starts with *any* allowed prefix, so a
    scope describes the union of its prefixes' subtrees. The intersection is
    therefore computed pairwise: for each ``(l, r)``, a path under both exists
    only when one prefix contains the other, and then the **narrower** one is
    the whole of that overlap.

    Returning ``left`` or ``right`` outright when the other is empty is correct
    — an empty list means "unrestricted", so the constraint is the other side's.
    """
    if not left:
        return right
    if not right:
        return left
    kept: list[str] = []
    for outer in left:
        for inner in right:
            if outer.startswith(inner):
                # ``inner`` is the broader prefix; ``outer`` is the overlap.
                kept.append(outer)
            elif inner.startswith(outer):
                kept.append(inner)
    return tuple(dict.fromkeys(kept))


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _clamp_depth(left: int, right: int) -> int:
    if left <= 0 or right <= 0:
        return 0
    return min(left, right) - 1


@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_tokens: int = 0
    max_model_calls: int = 0
    max_tool_calls: int = 0
    max_duration_seconds: float = 0.0
    max_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class Task:
    id: str = field(default_factory=lambda: str(uuid4()))
    workspace_id: str = ""
    instruction: str = ""
    actor: Principal = field(default_factory=lambda: Principal(user_id="system"))
    source: str = "unknown"
    status: TaskStatus = TaskStatus.CREATED
    delegation_scope: DelegationScope = field(default_factory=DelegationScope)
    budget: TaskBudget = field(default_factory=TaskBudget)
    phases: tuple[Phase, ...] = (
        Phase.UNDERSTAND,
        Phase.PLAN,
        Phase.EXECUTE,
        Phase.VERIFY,
        Phase.APPLY,
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    content: str = ""
    data_refs: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

"""Human approval workflow for risky executions (AUTHZ §5).

One mechanism, not two: the in-memory ``ApprovalTicketManager`` is gone, and
its semantics (a resource scope plus an action hash) now live on
:class:`ApprovalRecord`, which is persisted in the operational store.

Two behaviours are new:

* **Source grading** — an interactive session parks and asks a human, but a
  cron/automation task is denied outright by default (Hermes
  ``cron_mode: deny``), because nobody is watching.
* **Lifecycle** — approvals expire on their own. Sweeping turns stale PENDING
  records into EXPIRED so a task becomes retryable instead of waiting forever,
  and :meth:`ApprovalManager.oldest_pending_age` feeds the monitoring metric.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from Sprout.events import APPROVAL_DECIDED, APPROVAL_EXPIRED, APPROVAL_REQUESTED, Event, EventBus
from Sprout.task.models import UNATTENDED_SOURCES, TaskSource, coerce_source

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings
    from Sprout.security.audit import SecurityAuditLog


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


#: How many per-record locks to keep before pruning the released ones. An entry
#: is only dropped when its lock is unheld, which (asyncio semantics) also means
#: it has no waiters, so pruning cannot let two coroutines run concurrently.
_CONSUME_LOCK_CAP = 256


class ApprovalMode(StrEnum):
    """How a ``REQUIRE_APPROVAL`` decision is handled for a task source."""

    ASK = "ask"
    DENY = "deny"
    SANDBOX_ONLY = "sandbox_only"


@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    """Per-source approval behaviour (AUTHZ §5.3)."""

    unattended: ApprovalMode = ApprovalMode.DENY
    interactive: ApprovalMode = ApprovalMode.ASK
    mcp_client: ApprovalMode = ApprovalMode.ASK
    timeout_seconds: float = 3600.0

    @classmethod
    def from_settings(cls, security: SecuritySettings) -> ApprovalPolicy:
        settings = security.approvals
        try:
            unattended = ApprovalMode(settings.unattended)
        except ValueError:
            unattended = ApprovalMode.DENY
        return cls(unattended=unattended, timeout_seconds=settings.timeout_seconds)

    def mode_for(self, source: str | TaskSource | None) -> ApprovalMode:
        kind = coerce_source(source)
        if kind in UNATTENDED_SOURCES:
            return self.unattended
        if kind is TaskSource.MCP_CLIENT:
            return self.mcp_client
        return self.interactive

    def asks_a_human(self, source: str | TaskSource | None) -> bool:
        return self.mode_for(source) is ApprovalMode.ASK


@dataclass(slots=True)
class ApprovalRecord:
    """A single grant bound to an actor, task, action hash, and resource scope.

    Grants are never global: a record only ever authorises the task that
    requested it, and defaults to one-time use (Herness spec 11.5).
    """

    tool: str
    arguments_fingerprint: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str = "system"
    decided_by: str | None = None
    reason: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    task_id: str = ""
    single_use: bool = True
    expires_at: datetime | None = None
    used_at: datetime | None = None
    #: What the grant is limited to: a path glob, a URL, or a proposal id.
    resource_scope: str = ""
    #: Hash of the concrete action, so a grant can never drift to another one.
    action_hash: str = ""
    #: Redacted summary of the arguments, for the operator prompt and the audit
    #: trail. The fingerprint decides *matching*; this exists so a human can see
    #: what was approved — a hash answers nothing when read back later.
    action_summary: str = ""
    #: Which kind of session asked (``interactive``/``cron``/``mcp_client``...).
    source: str = "unknown"
    #: Conversation/session boundary for reusable approvals. Empty means a
    #: legacy or task-only approval that must not be reused across sessions.
    session_id: str = ""
    #: Coarse action class used only when ``single_use`` is false. This is what
    #: "approve similar" grants: same actor, same session, same source, same
    #: resource scope, same class.
    approval_class: str = ""

    @property
    def class_key(self) -> str:
        """Backward-compatible name for the reusable approval class."""
        return self.approval_class

    @class_key.setter
    def class_key(self, value: str) -> None:
        self.approval_class = value


def _resolve_suggestion_name(
    record: ApprovalRecord, registry: Any
) -> tuple[str, bool]:
    """``(name, came_from_a_real_command)`` for one approval record.

    ``action_summary`` is the redacted JSON of the approved arguments, written
    since that field was added. When it holds a ``command``, the name is a real
    ``argv[0]`` and the caller can act on it. Otherwise the fallback is the tool
    name, which is stable and recognisable but is *not* a command.
    """
    summary = getattr(record, "action_summary", "") or ""
    if summary:
        try:
            arguments = json.loads(summary)
        except (TypeError, ValueError):
            arguments = None
        if isinstance(arguments, Mapping):
            command = arguments.get("command")
            if isinstance(command, str) and command.strip():
                resolved = registry.name_of(command)
                if resolved:
                    return resolved, True
    return registry.name_of(record.tool), False


class ApprovalStore(Protocol):
    """Persistence contract for approval records; implemented by operational stores."""

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


class ApprovalManager:
    """Creates, queries, decides, and expires approval requests."""

    def __init__(
        self,
        store: ApprovalStore,
        *,
        events: EventBus | None = None,
        policy: ApprovalPolicy | None = None,
        audit: SecurityAuditLog | None = None,
        commands: Any | None = None,
    ) -> None:
        self._store = store
        self._events = events
        self._policy = policy or ApprovalPolicy()
        self._audit = audit
        self._commands = commands
        self._consume_locks: dict[str, asyncio.Lock] = {}

    @property
    def policy(self) -> ApprovalPolicy:
        return self._policy

    @property
    def store(self) -> ApprovalStore:
        """The backing store, exposed for read-only listing (CLI/Web)."""
        return self._store

    @staticmethod
    def describe(arguments: Mapping[str, Any], *, limit: int = 400) -> str:
        """A redacted, human-readable summary of what a grant would authorise.

        Recorded so "what did this approval actually cover?" stays answerable.
        The tool name alone cannot answer it — a ``cli_tool_run`` grant covers *a
        command line*, and which command line is exactly what an operator needs
        to review and an auditor needs to reconstruct.

        Redacted at the source rather than at each sink: the summary travels
        into the audit stream and the observation store, both durable, and a
        summary that is only sometimes scrubbed is a leak waiting for the first
        caller that forgets to.
        """
        if not arguments:
            return ""
        from Sprout.security.redact import Redactor

        rendered = json.dumps(
            dict(arguments), ensure_ascii=False, sort_keys=True, default=str
        )
        redacted = Redactor().scrub(rendered)
        return redacted[:limit] + "…" if len(redacted) > limit else redacted

    @staticmethod
    def fingerprint(arguments: Mapping[str, Any]) -> str:
        canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def class_key_for(self, tool: str, arguments: Mapping[str, Any]) -> str:
        """Return the coarse class behind an explicit "approve similar" grant.

        The full argument fingerprint remains the authority for one-time
        grants. Reusable grants need a stable, human-auditable class so changing
        incidental parameters within the same session does not ask again.
        """
        if tool != "cli_tool_run" or self._commands is None:
            return ""
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ""
        raw_args = arguments.get("args") or []
        argv = [command, *(str(item) for item in raw_args)] if isinstance(raw_args, list) else [command]
        return str(self._commands.class_key(argv))

    def mode_for(self, source: str | TaskSource | None) -> ApprovalMode:
        return self._policy.mode_for(source)

    def asks_a_human(self, source: str | TaskSource | None) -> bool:
        """False when this source may not wait for an approval at all."""
        return self._policy.asks_a_human(source)

    async def request(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        task_id: str = "",
        requested_by: str = "system",
        single_use: bool = True,
        ttl_seconds: float | None = None,
        resource_scope: str = "",
        action_hash: str = "",
        source: str = "unknown",
        session_id: str = "",
        request_approval: bool = True,
    ) -> ApprovalRecord:
        timeout = self._policy.timeout_seconds if ttl_seconds is None else ttl_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=timeout) if timeout else None
        record = ApprovalRecord(
            tool=tool,
            arguments_fingerprint=self.fingerprint(arguments),
            requested_by=requested_by,
            task_id=task_id,
            single_use=single_use,
            expires_at=expires_at,
            resource_scope=resource_scope,
            action_hash=action_hash or self.fingerprint({"tool": tool, **dict(arguments)}),
            action_summary=self.describe(arguments),
            source=coerce_source(source).value,
            session_id=session_id,
            approval_class=self.class_key_for(tool, arguments),
        )
        await self._store.save_approval(record)
        if request_approval:
            await self._emit(
                APPROVAL_REQUESTED,
                {
                    "approval_id": record.id,
                    "tool": tool,
                    "task_id": task_id,
                    "requested_by": requested_by,
                    "source": record.source,
                    "session_id": session_id,
                    "approval_class": record.approval_class,
                    "resource_scope": resource_scope,
                    "action_summary": record.action_summary,
                    "expires_at": expires_at.isoformat() if expires_at else "",
                },
            )
        return record

    async def find_pending(
        self, tool: str, arguments: Mapping[str, Any], *, task_id: str = ""
    ) -> ApprovalRecord | None:
        """An undecided request for the same action, if one is already open.

        Lets a concurrent batch of calls raise one prompt instead of one each,
        while still matching on the same task and action fingerprint, so the
        lookup can never return another task's request.
        """
        return await self._store.find_approval(
            tool, self.fingerprint(arguments), ApprovalStatus.PENDING, task_id
        )

    async def is_approved(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        task_id: str = "",
        session_id: str = "",
        requested_by: str = "system",
        source: str = "interactive",
        resource_scope: str = "",
    ) -> bool:
        """Consume one usable grant, atomically.

        The read-check-consume sequence used to be three bare awaits, so two
        concurrent callers could both observe ``APPROVED`` and both return
        ``True``: a one-time grant authorised its action twice. The lookup is
        still cheap-and-optimistic, but the decision and the consumption now
        happen inside a per-record lock, and the record is re-read there so a
        decision that landed in between is honoured rather than lost.
        """
        candidate = await self._store.find_approval(
            tool, self.fingerprint(arguments), ApprovalStatus.APPROVED, task_id
        )
        class_key = self.class_key_for(tool, arguments)
        if candidate is None and class_key and (session_id or task_id):
            candidate = await self._store.find_reusable_approval(
                tool,
                class_key,
                ApprovalStatus.APPROVED,
                session_id=session_id,
                requested_by=requested_by,
                source=coerce_source(source).value,
                task_id=task_id,
                resource_scope=resource_scope,
            )
        if candidate is None:
            return False
        async with self._consume_lock(candidate.id):
            record = await self._usable_record(
                tool,
                arguments,
                task_id=task_id,
                session_id=session_id,
                requested_by=requested_by,
                source=source,
                resource_scope=resource_scope,
            )
            if record is None:
                return False
            if record.single_use:
                record.status = ApprovalStatus.CONSUMED
                record.used_at = datetime.now(UTC)
                if not await self._store.save_approval_if_status(
                    record, ApprovalStatus.APPROVED
                ):
                    return False
            return True

    def _consume_lock(self, approval_id: str) -> asyncio.Lock:
        lock = self._consume_locks.get(approval_id)
        if lock is not None:
            return lock
        if len(self._consume_locks) >= _CONSUME_LOCK_CAP:
            for key in [
                key for key, held in self._consume_locks.items() if not held.locked()
            ]:
                del self._consume_locks[key]
        lock = asyncio.Lock()
        self._consume_locks[approval_id] = lock
        return lock

    async def _usable_record(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        task_id: str,
        session_id: str,
        requested_by: str,
        source: str,
        resource_scope: str,
    ) -> ApprovalRecord | None:
        record = await self._store.find_approval(
            tool, self.fingerprint(arguments), ApprovalStatus.APPROVED, task_id
        )
        class_key = self.class_key_for(tool, arguments)
        if record is None and class_key and (session_id or task_id):
            record = await self._store.find_reusable_approval(
                tool,
                class_key,
                ApprovalStatus.APPROVED,
                session_id=session_id,
                requested_by=requested_by,
                source=coerce_source(source).value,
                task_id=task_id,
                resource_scope=resource_scope,
            )
        if record is None:
            return None
        if record.task_id and record.task_id != task_id:
            return None
        scoped_to_session = bool(record.session_id)
        if scoped_to_session and record.session_id != session_id:
            return None
        if scoped_to_session and record.requested_by and record.requested_by != requested_by:
            return None
        if scoped_to_session and record.source and record.source != coerce_source(source).value:
            return None
        if scoped_to_session and record.resource_scope and record.resource_scope != resource_scope:
            return None
        if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
            record.status = ApprovalStatus.EXPIRED
            if not await self._store.save_approval_if_status(
                record, ApprovalStatus.APPROVED
            ):
                return None
            return None
        return record

    async def decide(
        self,
        approval_id: str,
        approved: bool,
        *,
        decided_by: str = "human",
        reason: str | None = None,
        channel: str = "cli",
    ) -> ApprovalRecord:
        if await self._store.get_approval(approval_id) is None:
            raise LookupError(f"Approval not found: {approval_id}")
        # Serialized per record and re-read inside the lock: two concurrent
        # decisions used to both observe PENDING and both write a verdict, so
        # the second one won the race instead of being rejected as already
        # decided.
        async with self._consume_lock(approval_id):
            record = await self._store.get_approval(approval_id)
            if record is None:
                raise LookupError(f"Approval not found: {approval_id}")
            if record.status is not ApprovalStatus.PENDING:
                if record.status is ApprovalStatus.APPROVED and approved:
                    return record
                raise ValueError(
                    f"Approval {approval_id} already decided: {record.status.value}"
                )
            return await self._apply_decision(
                record,
                approved,
                decided_by=decided_by,
                reason=reason,
                channel=channel,
            )

    async def _apply_decision(
        self,
        record: ApprovalRecord,
        approved: bool,
        *,
        decided_by: str,
        reason: str | None,
        channel: str,
    ) -> ApprovalRecord:
        if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
            # Too late to decide: settle the record as EXPIRED and report it
            # rather than raising, so the caller sees *why* nothing was granted.
            record.status = ApprovalStatus.EXPIRED
            record.decided_at = datetime.now(UTC)
            record.reason = "Expired before a decision arrived"
            if not await self._store.save_approval_if_status(
                record, ApprovalStatus.PENDING
            ):
                current = await self._store.get_approval(record.id)
                if current is not None:
                    return current
                raise LookupError(f"Approval not found: {record.id}")
            await self._audit_decision(record, channel=channel)
            await self._emit(
                APPROVAL_EXPIRED,
                {"approval_id": record.id, "task_id": record.task_id},
            )
            return record
        record.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        record.decided_by = decided_by
        record.reason = reason
        record.decided_at = datetime.now(UTC)
        if not await self._store.save_approval_if_status(
            record, ApprovalStatus.PENDING
        ):
            current = await self._store.get_approval(record.id)
            if current is not None and current.status is ApprovalStatus.APPROVED and approved:
                return current
            raise ValueError(f"Approval {record.id} was decided concurrently")
        await self._audit_decision(record, channel=channel)
        await self._emit(
            APPROVAL_DECIDED,
            {
                "approval_id": record.id,
                "tool": record.tool,
                "approved": approved,
                "decided_by": decided_by,
                "task_id": record.task_id,
                "channel": channel,
            },
        )
        return record

    async def pending(self) -> list[ApprovalRecord]:
        return list(await self._store.list_approvals(ApprovalStatus.PENDING))

    async def sweep_expired(self, *, now: datetime | None = None) -> int:
        """Move stale PENDING records to EXPIRED; returns how many were swept."""
        current = now or datetime.now(UTC)
        swept = 0
        for record in await self._store.list_approvals(ApprovalStatus.PENDING):
            if record.expires_at is None or record.expires_at > current:
                continue
            record.status = ApprovalStatus.EXPIRED
            record.decided_at = current
            record.reason = record.reason or "Expired without a decision"
            if not await self._store.save_approval_if_status(
                record, ApprovalStatus.PENDING
            ):
                continue
            swept += 1
            await self._emit(
                APPROVAL_EXPIRED,
                {"approval_id": record.id, "task_id": record.task_id, "tool": record.tool},
            )
        return swept

    async def oldest_pending_age(self, *, now: datetime | None = None) -> float | None:
        """Age of the oldest PENDING approval in seconds (monitoring metric)."""
        pending = await self.pending()
        if not pending:
            return None
        current = now or datetime.now(UTC)
        return max((current - record.created_at).total_seconds() for record in pending)

    async def suggest_allowlist(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Propose commands the operator keeps approving, most frequent first.

        Two things were wrong with the first version, and together they made the
        whole feature useless rather than merely untidy:

        * It emitted one row per *approval record*, so nineteen grants for the
          same tool produced nineteen identical suggestions — the list was
          20 copies of ``cli_tool_run`` and nothing else.
        * It proposed ``record.tool``. What the command policy gates is
          ``argv[0]`` (``git``, ``sprout``, ``pytest``), matched by
          ``CommandRegistry.name_of``; a *tool* name like ``cli_tool_run``
          matches no command and is not what ``auto_run`` is keyed on. So
          applying the suggestion changed nothing about how anything was
          approved.

        The command name is recovered from ``action_summary`` when present (it
        carries the real argv). A record written before that field existed has
        only its tool name, and ``cli_tool_run`` is not a command — ``auto_run``
        can never match it. Those are reported as ``actionable: False`` rather
        than offered as a change that would silently do nothing.
        """
        from Sprout.security.commands import CommandRegistry

        registry = CommandRegistry()
        approved = await self._store.list_approvals(ApprovalStatus.APPROVED)

        # Group by the name that policy actually keys on, counting how often the
        # operator has granted it.
        tally: dict[str, dict[str, Any]] = {}
        for record in approved:
            name, derived_from_command = _resolve_suggestion_name(record, registry)
            if not name or registry.is_allowlisted(name):
                continue
            entry = tally.setdefault(
                name,
                {
                    "tool": name,
                    "approvals": 0,
                    # A name recovered from the real argv is something auto_run
                    # can act on; a tool name is not.
                    "actionable": derived_from_command,
                    "resource_scope": record.resource_scope,
                    "task_id": record.task_id,
                },
            )
            entry["approvals"] += 1

        suggestions = sorted(
            tally.values(),
            key=lambda item: (not item["actionable"], -item["approvals"], item["tool"]),
        )
        return suggestions[:limit]

    async def _audit_decision(self, record: ApprovalRecord, *, channel: str) -> None:
        if self._audit is None:
            return
        from Sprout.security.audit import KIND_APPROVAL_DECISION

        self._audit.record(
            KIND_APPROVAL_DECISION,
            {
                "approval_id": record.id,
                "tool": record.tool,
                "actor": record.decided_by or "",
                "requested_by": record.requested_by,
                "task_id": record.task_id,
                "session_id": record.session_id,
                "resource_scope": record.resource_scope,
                "approval_class": record.approval_class,
                # Already redacted by ``describe``; recorded so the audit lane
                # answers "what did this grant cover?" without a join into a
                # conversation turn that may since have been compacted away.
                "action_summary": record.action_summary,
                "decision": record.status.value,
                "channel": channel,
            },
        )

    async def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            await self._events.publish(Event(name, payload))

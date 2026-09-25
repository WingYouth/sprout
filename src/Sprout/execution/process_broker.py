"""Policy-controlled subprocess execution (AUTHZ §4.3, §6.1).

Two behaviours changed with the authorization work:

* ``known_command`` is no longer an input. It travelled in the model's tool
  arguments, so the model could attest to itself. The broker now derives it from
  :class:`~Sprout.security.commands.CommandRegistry` by inspecting ``argv[0]``;
  a caller-supplied ``known_command`` is ignored and reported as
  ``auth.self_attestation_ignored``.
* child processes get a **whitelisted** environment instead of inheriting the
  parent's, so an unrelated API key cannot leak into a subprocess. Extra
  variables are injected explicitly by name.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.execution.models import ProcessResult
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.execution.proc import terminate as _terminate
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.commands import CommandRegistry
from Sprout.security.engine import PolicyEngine
from Sprout.security.secret_broker import SecretBroker
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace

if TYPE_CHECKING:
    from Sprout.events import EventBus
    from Sprout.security.approval import ApprovalManager
    from Sprout.security.audit import SecurityAuditLog

#: Approval key for a withheld command. One grant per task covers its
#: verification commands, so a six-command round asks once rather than six
#: times — the arguments (and so the fingerprint) differ per command, which is
#: what `is_approved` compares.
APPROVAL_TOOL = "process_run"


class ProcessBroker:
    """Runs structured process requests only after a PolicyEngine decision."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        default_timeout: float = 60.0,
        commands: CommandRegistry | None = None,
        secrets: SecretBroker | None = None,
        events: EventBus | None = None,
        audit: SecurityAuditLog | None = None,
        extra_env_names: Sequence[str] = (),
        approvals: ApprovalManager | None = None,
    ) -> None:
        self._policy = policy
        self._default_timeout = default_timeout
        self._commands = commands or CommandRegistry()
        self._secrets = secrets or SecretBroker()
        self._events = events
        self._audit = audit
        self._extra_env_names = tuple(extra_env_names)
        # Without a manager, REQUIRE_APPROVAL stays a refusal — the previous
        # behaviour, and the fail-safe default when none is wired.
        self._approvals = approvals

    @property
    def commands(self) -> CommandRegistry:
        return self._commands

    async def run(
        self,
        workspace: Workspace,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        known_command: bool = False,
        task_id: str = "",
        session_id: str = "",
        secret_names: Sequence[str] = (),
        required_env: Sequence[str] = (),
        scope: DelegationScope | None = None,
        command_origin: str = "caller",
        source: str = "interactive",
        requested_by: str = "system",
        resource_scope: str = "",
        upstream_approval_granted: bool = False,
    ) -> ProcessResult:
        command_tuple = tuple(str(part) for part in command)
        cwd_path = Path(cwd or workspace.root)
        resource = ResourceRef(
            workspace_id=workspace.id,
            path=str(cwd_path),
            kind=ResourceKind.CONFIG,
        )
        if known_command:
            # Caller-supplied attestation is not evidence; the allowlist is.
            await self._notify_self_attestation(command_tuple, task_id)
        tags = self._commands.tag(command_tuple)
        request = ActionRequest(
            task_id=task_id,
            action=ActionType.PROCESS_RUN,
            resource=resource,
            arguments={
                "command": list(command_tuple),
                # Where the command came from. ``manifest`` means the workspace
                # scanner inferred it, which is the case worth auditing: those
                # run inside the directory the task just wrote to.
                "command_origin": command_origin,
                **tags,
            },
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        allowlisted = bool(tags["allowlisted_command"])
        self._record_allowlist(command_tuple, allowlisted, command_origin, task_id)
        if decision.decision is not AccessDecision.ALLOW:
            blocked = await self._withheld(
                command_tuple,
                decision,
                request,
                resource_scope=resource_scope,
                task_id=task_id,
                session_id=session_id,
                requested_by=requested_by,
                source=source,
                allowlisted=allowlisted,
                upstream_approval_granted=upstream_approval_granted,
            )
            if blocked is not None:
                return blocked
            # An existing grant covers it: fall through and run.

        started = time.perf_counter()
        process_env = self._secrets.child_env(
            base_env=os.environ,
            required=(*required_env, *self._extra_env_names),
            extra=env,
            secret_names=secret_names,
        )
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command_tuple,
                cwd=str(cwd_path),
                env=process_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds or self._default_timeout,
            )
        except TimeoutError:
            if process is not None:
                await _terminate(process)
            return ProcessResult(
                command=command_tuple,
                exit_code=None,
                duration_ms=(time.perf_counter() - started) * 1000,
                allowed=True,
                error="Process timed out",
                allowlisted=allowlisted,
            )
        except OSError as exc:
            return ProcessResult(
                command=command_tuple,
                exit_code=None,
                duration_ms=(time.perf_counter() - started) * 1000,
                allowed=True,
                error=f"{type(exc).__name__}: {exc}",
                allowlisted=allowlisted,
            )

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        # Redaction is unconditional: patterns catch credentials that were never
        # declared as secrets and therefore never entered the injection list.
        stdout_result = self._secrets.redact_result(stdout_text, secret_names)
        stderr_result = self._secrets.redact_result(stderr_text, secret_names)
        return ProcessResult(
            command=command_tuple,
            exit_code=process.returncode,
            stdout=stdout_result.text,
            stderr=stderr_result.text,
            duration_ms=(time.perf_counter() - started) * 1000,
            allowed=True,
            allowlisted=allowlisted,
            redactions=stdout_result.count + stderr_result.count,
        )

    async def _withheld(
        self,
        command: tuple[str, ...],
        decision: Any,
        request: ActionRequest,
        *,
        resource_scope: str,
        task_id: str,
        session_id: str,
        requested_by: str,
        source: str,
        allowlisted: bool,
        upstream_approval_granted: bool = False,
    ) -> ProcessResult | None:
        """Handle a non-ALLOW decision: park on approval, refuse, or proceed.

        Returns ``None`` when an existing grant covers the command, meaning the
        caller should run it. This used to return ``allowed=False`` for every
        non-ALLOW verdict including REQUIRE_APPROVAL — so verification commands
        were refused outright and *nobody was ever asked*. Every EVALUATION
        round reported failure while executing nothing, and a change could
        reach approval with no test having run.

        Now the broker asks, mirroring ``ToolExecutor``. The security posture
        is unchanged: approval is still required, which is the point, since a
        worktree sandbox is a logical boundary rather than an OS one and these
        commands execute code the task just wrote.
        """
        withheld = ProcessResult(
            command=command,
            allowed=False,
            error=decision.reason,
            allowlisted=allowlisted,
        )
        if decision.decision is not AccessDecision.REQUIRE_APPROVAL:
            return withheld
        # ``ToolExecutor`` has already granted this exact CLI invocation. Its
        # internal context is injected server-side and is never part of the
        # user arguments, so the broker can honor it without asking twice.
        # A DENY is handled above and can never be relaxed here.
        if upstream_approval_granted:
            return None
        if self._approvals is None:
            return replace(
                withheld,
                error=f"{decision.reason} (no approval manager is configured)",
            )
        if not self._approvals.asks_a_human(source):
            # Unattended source: no decision can arrive, so fail closed rather
            # than park a task nobody will ever answer.
            return replace(
                withheld,
                error=(
                    f"{decision.reason} (source {source!r} is unattended, "
                    f"mode: {self._approvals.mode_for(source).value})"
                ),
            )
        # Task-scoped, not command-scoped: the approval arguments deliberately
        # carry no command, so one grant covers a whole verification round.
        # Keyed per command, a six-command round would ask six times, which no
        # one would use — and `is_approved` compares a fingerprint of these
        # arguments, so omitting the command is what makes one grant reusable.
        approval_arguments = {
            "action": "verification_commands",
            "task_id": task_id,
            "resource_scope": resource_scope,
        }
        if await self._approvals.is_approved(
            APPROVAL_TOOL,
            approval_arguments,
            task_id=task_id,
            session_id=session_id,
            requested_by=requested_by,
            source=source,
            resource_scope=resource_scope,
        ):
            return None  # granted: run it
        existing = await self._approvals.find_pending(
            APPROVAL_TOOL, approval_arguments, task_id=task_id
        )
        if existing is not None:
            # A round runs its commands concurrently, so without this each one
            # would raise its own request and the operator would face five
            # identical prompts for one decision.
            return replace(withheld, approval_id=existing.id)
        record = await self._approvals.request(
            APPROVAL_TOOL,
            approval_arguments,
            task_id=task_id,
            requested_by=requested_by,
            resource_scope=resource_scope,
            source=source,
            session_id=session_id,
            # Reusable so the rest of the round lands on the same grant; still
            # bounded by task_id and expiry.
            single_use=False,
        )
        return replace(withheld, approval_id=record.id)

    def _record_allowlist(
        self,
        command: tuple[str, ...],
        allowlisted: bool,
        command_origin: str,
        task_id: str,
    ) -> None:
        """Audit the allowlist verdict (AUTHZ §7.4).

        ``command.allowlisted`` is declared ``bus_event=False`` in the catalog:
        it belongs on the security audit stream, not the event bus. Recording
        never raises into the caller's path.
        """
        if self._audit is None:
            return
        from Sprout.security.audit import KIND_COMMAND_ALLOWLISTED

        self._audit.record(
            KIND_COMMAND_ALLOWLISTED,
            {
                "command": list(command),
                "argv0": command[0] if command else "",
                "allowlisted": allowlisted,
                "command_origin": command_origin,
                "task_id": task_id,
            },
        )

    async def _notify_self_attestation(
        self, command: tuple[str, ...], task_id: str
    ) -> None:
        if self._events is None:
            return
        from Sprout.events import AUTH_SELF_ATTESTATION_IGNORED, Event

        await self._events.publish(
            Event(
                AUTH_SELF_ATTESTATION_IGNORED,
                {"command": list(command), "task_id": task_id},
            )
        )

"""Security-gated tool execution (AUTHZ §1.1, §5.3).

The tool path speaks the same vocabulary as the brokers now: ``SecurityPolicy``
returns a :class:`~Sprout.security.access.PolicyDecision` (with a ``risk:*``
provenance rule) instead of its own enum, and every decision can be written to
the security audit stream.

Approvals are graded by where the call came from: an interactive session parks
and asks a human, while a cron/automation session is denied outright because
nobody is watching (Hermes ``cron_mode: deny``).

Fail-safe rule: when a call requires approval but no approval manager is
wired, the call is denied rather than executed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from Sprout.events import (
    APPROVAL_REQUESTED,
    TOOL_DENIED,
    TOOL_EXECUTED,
    Event,
    EventBus,
)
from Sprout.security.access import AccessDecision
from Sprout.security.approval import ApprovalManager
from Sprout.security.policy import Decision, SecurityPolicy
from Sprout.tools.context_keys import CONTEXT_KEY, CONTEXT_TOOLS
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.result import ToolResult

if TYPE_CHECKING:
    from Sprout.security.audit import SecurityAuditLog

__all__ = ["Decision", "ToolExecutor"]


@dataclass(slots=True)
class ToolExecutor:
    """Runs one tool call through the security policy before invoking it.

    ``scoped`` carries the tools a single node was given. Node tools take
    precedence over ``tools``, which stays the process-wide registry for the
    security floor's risk lookup and the ``tool_run`` meta-tool. Keeping node
    tools in a per-run overlay instead of registering them globally is what
    lets concurrent nodes each run with their own set — the previous
    register/unregister pair was a race, not just untidy.
    """

    tools: ToolRegistry
    policy: SecurityPolicy = field(default_factory=SecurityPolicy)
    approvals: ApprovalManager | None = None
    events: EventBus | None = None
    audit: SecurityAuditLog | None = None
    #: Server-side command facts, used to recognise a read-only ``cli_tool_run``
    #: and skip the prompt for it. ``None`` keeps the old behaviour: every
    #: ``cli_tool_run`` asks.
    commands: Any | None = None
    #: Node-scoped tools consulted before ``tools``. ``None`` means "no node
    #: scope", which is the interactive path.
    scoped: Mapping[str, Any] | None = None

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        requested_by: str = "unknown",
        task_id: str = "",
        session_id: str = "",
        source: str = "interactive",
        resource_scope: str = "",
    ) -> ToolResult:
        try:
            tool = self._resolve(name)
        except KeyError:
            return ToolResult.failure(f"Unknown tool: {name}")
        except LookupError as exc:
            return ToolResult.failure(str(exc))

        decision = self.policy.decide_for_spec(tool.spec)

        # A read-only command is granted without asking. This runs *after* the
        # policy decision and only ever relaxes REQUIRE_APPROVAL — a DENY still
        # denies, and the check is on the arguments (the actual argv) rather
        # than on the tool, because ``cli_tool_run`` is one tool for both
        # ``git status`` and ``git push``.
        read_only = decision.decision is AccessDecision.REQUIRE_APPROVAL and (
            self._is_read_only_invocation(name, arguments)
        )
        if read_only:
            decision = replace(
                decision,
                decision=AccessDecision.ALLOW,
                reason=f"{decision.reason}; read-only invocation",
                matched_rules=(*decision.matched_rules, "readonly:cli_tool_run"),
            )

        await self._audit(name, task_id, source, decision.decision.value, decision.reason)

        if decision.decision is AccessDecision.DENY:
            await self._publish(TOOL_DENIED, {"tool": name, "reason": "policy"})
            return ToolResult.denied(f"Tool {name} is denied by the security policy")

        approval_granted = False
        if decision.decision is AccessDecision.REQUIRE_APPROVAL:
            if self.approvals is None:
                await self._publish(TOOL_DENIED, {"tool": name, "reason": "no-approval-manager"})
                return ToolResult.denied(
                    f"Tool {name} requires approval, but no approval manager is configured"
                )
            mode = self.approvals.mode_for(source)
            if not self.approvals.asks_a_human(source):
                # cron / automation: nobody is watching, so no human decision
                # can arrive. Fail closed instead of parking the task forever.
                await self._publish(
                    TOOL_DENIED,
                    {"tool": name, "reason": "unattended", "mode": mode.value},
                )
                return ToolResult.denied(
                    f"Tool {name} requires approval and source {source!r} is "
                    f"unattended (mode: {mode.value})"
                )
            approval_granted = await self.approvals.is_approved(
                name,
                arguments,
                task_id=task_id,
                session_id=session_id,
                requested_by=requested_by,
                source=source,
                resource_scope=resource_scope,
            )
            if not approval_granted:
                record = await self.approvals.request(
                    name,
                    arguments,
                    task_id=task_id,
                    requested_by=requested_by,
                    resource_scope=resource_scope,
                    source=source,
                    session_id=session_id,
                )
                await self._publish(
                    APPROVAL_REQUESTED, {"tool": name, "approval_id": record.id}
                )
                return ToolResult.needs_approval(record.id)

        try:
            contextual = self._with_context(
                name,
                arguments,
                task_id,
                session_id,
                source,
                requested_by,
                approval_granted=approval_granted,
            )
            result = await tool.invoke(contextual)
        except Exception as exc:  # noqa: BLE001 - tool errors must not break the loop
            await self._publish(TOOL_EXECUTED, {"tool": name, "ok": False})
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")
        await self._publish(TOOL_EXECUTED, {"tool": name, "ok": result.ok})
        return result

    def _is_read_only_invocation(self, name: str, arguments: Mapping[str, Any]) -> bool:
        """True when this call is a command that only reads.

        Only ``cli_tool_run`` is considered, and only when a command registry is
        wired. Everything else keeps the policy decision it was given — the
        point is to stop re-asking about ``pwd`` and ``git status``, not to
        widen what the runtime will run.
        """
        if self.commands is None or name != "cli_tool_run":
            return False
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return False
        raw_args = arguments.get("args") or []
        if not isinstance(raw_args, (list, tuple)):
            return False
        argv = [command, *(str(item) for item in raw_args)]
        from Sprout.security.commands import is_read_only_command

        try:
            return is_read_only_command(argv, registry=self.commands)
        except Exception:  # noqa: BLE001 - a classification bug must not grant
            return False

    def _with_context(
        self,
        name: str,
        arguments: Mapping[str, Any],
        task_id: str,
        session_id: str,
        source: str,
        requested_by: str,
        *,
        approval_granted: bool = False,
    ) -> Mapping[str, Any]:
        """Attach the calling context a tool cannot otherwise see.

        A tool only receives its ``arguments`` (``Tool.invoke``), so a tool that
        delegates onward — ``cli_tool_run`` handing a command to
        ``ProcessBroker`` — has no way to tell the next layer *which task* and
        *which source* it is acting for. The broker then evaluates its own
        ``process_run`` gate with an empty task id, cannot match the grant the
        operator just issued for the outermost tool, and refuses a call that was
        already approved.

        Injected **after** the decision and fingerprinting above, under a
        reserved key tools are expected to strip rather than forward into their
        own policy arguments: including it in a fingerprint would make one
        approval stop covering the same call replayed in a new turn.
        """
        if name not in CONTEXT_TOOLS:
            return arguments
        return {
            **arguments,
            CONTEXT_KEY: {
                "task_id": task_id,
                "session_id": session_id,
                "source": source,
                "requested_by": requested_by,
                "approval_granted": approval_granted,
            },
        }

    def _resolve(self, name: str) -> Any:
        """Node-scoped tool if the current node has one, else the registry."""
        if self.scoped is not None and name in self.scoped:
            return self.scoped[name]
        return self.tools.get(name)

    def with_scoped_tools(self, tools: Mapping[str, Any]) -> ToolExecutor:
        """A copy dispatching to ``tools`` first, for one node's run.

        A copy rather than a mutation: concurrent nodes must not see each
        other's tool set.
        """
        clone = replace(self, scoped=dict(tools))
        return clone

    async def _audit(
        self, tool: str, task_id: str, source: str, decision: str, reason: str
    ) -> None:
        if self.audit is None:
            return
        from Sprout.security.audit import KIND_POLICY_DECISION

        self.audit.record(
            KIND_POLICY_DECISION,
            {
                "action": "tool.invoke",
                "resource": tool,
                "tool": tool,
                "task_id": task_id,
                "source": source,
                "decision": decision,
                "reason": reason,
            },
        )

    async def _publish(self, name: str, payload: dict[str, Any]) -> None:
        if self.events is not None:
            await self.events.publish(Event(name, payload))


# Re-exported so callers that still import the tool-risk vocabulary keep working.

"""One wiring object for the whole authorization layer (AUTHZ §8).

Assembling the pieces separately in the CLI, the web API, and the MCP server is
how the three policy engines drifted apart in the first place. Everything a
caller needs to enforce authorization now comes out of
:meth:`SecurityLayer.from_settings`:

* the layered policy engine (hard floor -> matrix -> layers -> risk);
* the command allowlist that replaced model-supplied ``known_command``;
* the secret broker (injection + one redactor);
* the SSRF guard;
* the audit stream;
* the approval manager and its per-source policy.

The layer deliberately holds data, not brokers, so importing it cannot create a
cycle with ``Sprout.execution`` or ``Sprout.workspace``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from Sprout.security.approval import ApprovalManager, ApprovalPolicy
from Sprout.security.audit import SecurityAuditLog
from Sprout.security.audit_emit import make_audit_failure_hook
from Sprout.security.commands import CommandRegistry
from Sprout.security.layered_policy import LayeredPolicyEngine
from Sprout.security.net_guard import NetworkGuard
from Sprout.security.policy import SecurityPolicy
from Sprout.security.secret_broker import SecretBroker

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings
    from Sprout.events import EventBus
    from Sprout.security.approval import ApprovalStore


@dataclass(frozen=True, slots=True)
class SecurityLayer:
    """The assembled authorization layer for one runtime."""

    policy_engine: LayeredPolicyEngine
    audit: SecurityAuditLog
    commands: CommandRegistry
    secrets: SecretBroker
    guard: NetworkGuard
    approval_policy: ApprovalPolicy
    approvals: ApprovalManager | None = None
    extra_env_names: tuple[str, ...] = ()
    tool_policy: SecurityPolicy = field(default_factory=SecurityPolicy)
    #: ``[security.classify]`` glob -> ResourceKind overrides, shared by the read
    #: broker, the file broker and the workspace scanner so that classification
    #: cannot drift between callers.
    classify_overrides: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_settings(
        cls,
        security: SecuritySettings,
        *,
        store: ApprovalStore | None = None,
        events: EventBus | None = None,
        secrets: SecretBroker | None = None,
        tool_risk_lookup: Callable[[str], str] | None = None,
    ) -> SecurityLayer:
        audit = SecurityAuditLog.from_settings(security)
        if events is not None:
            audit.on_failure = make_audit_failure_hook(events)
        approval_policy = ApprovalPolicy.from_settings(security)
        commands = CommandRegistry.from_settings(security)
        approvals = (
            ApprovalManager(
                store,
                events=events,
                policy=approval_policy,
                audit=audit,
                commands=commands,
            )
            if store is not None and security.require_approval
            else None
        )
        return cls(
            policy_engine=LayeredPolicyEngine.from_settings(
                security, audit=audit, tool_risk_lookup=tool_risk_lookup
            ),
            audit=audit,
            commands=commands,
            secrets=secrets or SecretBroker(),
            guard=NetworkGuard.from_settings(security),
            approval_policy=approval_policy,
            approvals=approvals,
            extra_env_names=tuple(security.commands.inherit_env),
            tool_policy=SecurityPolicy(allow_medium_risk=security.allow_medium_risk),
            classify_overrides=dict(security.classify.rules),
        )

    def describe(self) -> dict[str, object]:
        """Small, non-secret summary for ``sprout info``."""
        return {
            "floor_rules": list(self.policy_engine.floor),
            "layers": [layer.name for layer in self.policy_engine.layers],
            "command_allowlist": sorted(self.commands.allowlist),
            "command_denylist": sorted(self.commands.denylist),
            # What may run with no approval at all. Empty by default, so this is
            # the line an operator checks after adding to auto_run.
            "command_auto_run": sorted(self.commands.auto_run),
            "audit_path": str(self.audit.path),
            "audit_enabled": self.audit.enabled,
            "unattended_approval": self.approval_policy.unattended.value,
            "private_host_allowlist": list(self.guard.allow_private),
            "blocked_domains": list(self.guard.blocked_domains),
            "classify_overrides": dict(self.classify_overrides),
        }

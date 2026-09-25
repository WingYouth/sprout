"""Risk-based tool execution policy (AUTHZ §1.1).

``SecurityPolicy`` used to be a third, independent decision maker sitting beside
``PolicyEngine`` and ``LayeredPolicyEngine``. It now speaks the same vocabulary:
:meth:`SecurityPolicy.evaluate` returns a
:class:`~Sprout.security.access.PolicyDecision` with provenance, and is wired
into :class:`~Sprout.security.layered_policy.LayeredPolicyEngine` as the *risk
floor* layer. A tool's declared risk level can therefore only tighten the
matrix decision — it can never widen a ``DENY``.

Rules, from most to least specific:

1. ``always_allow`` / ``always_deny`` match by tool name (deny wins).
2. CRITICAL risk is always denied.
3. HIGH risk always requires approval.
4. MEDIUM risk is allowed unless ``allow_medium_risk`` is False.
5. LOW risk is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from Sprout.security.access import AccessDecision, PolicyDecision
from Sprout.security.risk import RiskLevel

if TYPE_CHECKING:
    from Sprout.tools.spec import ToolSpec


class Decision(StrEnum):
    """Tool-risk vocabulary, kept for callers that predate the unified protocol."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Decides whether a tool call may run, needs human approval, or is denied."""

    allow_medium_risk: bool = True
    always_allow: frozenset[str] = frozenset()
    always_deny: frozenset[str] = frozenset()

    def evaluate(self, *, tool: str, risk_level: str = "") -> PolicyDecision:
        """The unified entry point: tool name + declared risk -> policy decision."""
        if tool in self.always_deny:
            return PolicyDecision(
                decision=AccessDecision.DENY,
                reason=f"Tool {tool} is on the hard deny list",
                matched_rules=(f"risk:always_deny:{tool}",),
            )
        if tool in self.always_allow:
            return PolicyDecision(
                decision=AccessDecision.ALLOW,
                reason=f"Tool {tool} is explicitly allowed",
                matched_rules=(f"risk:always_allow:{tool}",),
            )
        risk = RiskLevel.coerce(risk_level)
        if risk is RiskLevel.CRITICAL:
            return PolicyDecision(
                decision=AccessDecision.DENY,
                reason=f"Tool {tool} is critical risk",
                matched_rules=("risk:critical",),
            )
        if risk is RiskLevel.HIGH:
            return PolicyDecision(
                decision=AccessDecision.REQUIRE_APPROVAL,
                reason=f"Tool {tool} is high risk",
                matched_rules=("risk:high",),
            )
        if risk is RiskLevel.MEDIUM and not self.allow_medium_risk:
            return PolicyDecision(
                decision=AccessDecision.REQUIRE_APPROVAL,
                reason=f"Tool {tool} is medium risk and medium risk is not allowed",
                matched_rules=("risk:medium:gated",),
            )
        return PolicyDecision(
            decision=AccessDecision.ALLOW,
            reason="",
            matched_rules=(f"risk:{risk.value}",),
        )

    def decide_for_spec(self, spec: ToolSpec) -> PolicyDecision:
        """Convenience for callers that already hold the tool spec."""
        return self.evaluate(tool=spec.name, risk_level=spec.risk_level)

    def check(self, spec: ToolSpec) -> Decision:
        """Legacy wrapper returning the tool-risk enum."""
        decision = self.decide_for_spec(spec).decision
        if decision is AccessDecision.DENY:
            return Decision.DENY
        if decision is AccessDecision.REQUIRE_APPROVAL:
            return Decision.REQUIRE_APPROVAL
        return Decision.ALLOW

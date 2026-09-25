"""Layered policy intersection with provenance (AUTHZ §1.1-§1.5).

Layers are applied to the base matrix decision in a fixed order — organization,
workspace, delegation, then the tool-risk floor — and every step can only
tighten. ``PolicyDecision.matched_rules`` records ``<layer>:<rule id>`` for each
participating rule, which is what the audit stream and the approval prompt show.

Rules are declarative now: ``PolicyRule`` understands path globs (``fnmatch``,
replacing bare ``startswith``), actor roles, resource kinds, and argument
guards, and the whole set can be assembled from ``[security.rules]`` in
``sprout.toml``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import TYPE_CHECKING

from Sprout.security.access import AccessDecision, ActionRequest, PolicyDecision
from Sprout.security.engine import PolicyEngine
from Sprout.security.policy import SecurityPolicy

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings
    from Sprout.security.audit import SecurityAuditLog
    from Sprout.security.protocol import PolicyEngineProtocol

#: Operator-declared organization denies, applied to ``process.run`` commands.
#: Mirrors Hermes' ``approvals.deny`` globs.
DEFAULT_ORGANIZATION_DENY: tuple[str, ...] = ("git push --force*", "git push -f*")

_COMMAND_ARGUMENT = "command"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """One declarative rule.

    ``argument_guards`` maps an argument name to a guard spec:
    ``glob:<pattern>``, ``equals:<value>``, ``contains:<substring>``, or
    ``allowlist:<name>`` (the argument value is looked up in
    :mod:`Sprout.security.commands`). Sequence arguments are joined with spaces
    before matching, so ``command = ["git", "push", "--force"]`` is guarded by
    ``glob:git push --force*``.
    """

    action: str = "*"
    path_glob: str = "*"
    actor_role: str = ""
    resource_kind: str = ""
    argument_guards: Mapping[str, str] = field(default_factory=dict)
    decision: AccessDecision = AccessDecision.DENY
    id: str = ""

    def matches(self, request: ActionRequest) -> bool:
        if self.action not in {"", "*", request.action.value}:
            return False
        if self.actor_role and not _actor_matches(request, self.actor_role):
            return False
        if self.resource_kind:
            kind = request.resource.kind.value if request.resource is not None else ""
            if kind != self.resource_kind:
                return False
        path = request.resource.path if request.resource is not None else ""
        if self.path_glob and not fnmatch(path, self.path_glob):
            return False
        return all(
            _guard_matches(request.arguments.get(name), spec)
            for name, spec in self.argument_guards.items()
        )


def _actor_matches(request: ActionRequest, role: str) -> bool:
    actor = request.actor
    return actor.user_id == role or actor.has_role(role)


def _guard_matches(value: object, spec: str) -> bool:
    if isinstance(value, (list, tuple)):
        text = " ".join(str(part) for part in value)
    elif isinstance(value, str):
        text = value
    else:
        return False
    kind, _, operand = spec.partition(":")
    if kind == "glob":
        return fnmatch(text, operand)
    if kind == "equals":
        return text == operand
    if kind == "contains":
        return operand in text
    if kind == "allowlist":
        from Sprout.security.commands import DEFAULT_COMMAND_ALLOWLIST

        return text.split()[0].casefold() in {name.casefold() for name in DEFAULT_COMMAND_ALLOWLIST}
    return False


class PolicyLayer:
    """A named, ordered rule set; the first matching rule wins."""

    def __init__(self, name: str, rules: Sequence[PolicyRule] = ()) -> None:
        self.name = name
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[PolicyRule, ...]:
        return self._rules

    def match(self, request: ActionRequest) -> PolicyRule | None:
        for rule in self._rules:
            if rule.matches(request):
                return rule
        return None

    @classmethod
    def from_mapping(cls, name: str, mapping: Mapping[str, str]) -> PolicyLayer:
        """Build a layer from ``{"file.read:src/**": "allow"}`` config entries."""
        rules: list[PolicyRule] = []
        for key, value in mapping.items():
            action, _, path_glob = key.partition(":")
            try:
                decision = AccessDecision(value)
            except ValueError as exc:
                raise ValueError(f"Unknown decision {value!r} for rule {key!r}") from exc
            rules.append(
                PolicyRule(
                    action=action.strip() or "*",
                    path_glob=path_glob.strip() or "*",
                    decision=decision,
                    id=f"{name}:{key}",
                )
            )
        return cls(name, rules)

    @classmethod
    def from_command_globs(
        cls,
        name: str,
        globs: Sequence[str],
        *,
        decision: AccessDecision = AccessDecision.DENY,
        prefix: str = "deny",
    ) -> PolicyLayer:
        """Build a ``process.run`` command-glob layer (Hermes ``approvals.deny``)."""
        return cls(
            name,
            tuple(
                PolicyRule(
                    action="process.run",
                    argument_guards={_COMMAND_ARGUMENT: f"glob:{pattern}"},
                    decision=decision,
                    id=f"{name}:{prefix}:{pattern}",
                )
                for pattern in globs
            ),
        )


class LayeredPolicyEngine:
    """Applies the base matrix, then organization, workspace, delegation, risk."""

    def __init__(
        self,
        base: PolicyEngineProtocol | None = None,
        *,
        organization: PolicyLayer | None = None,
        workspace: PolicyLayer | None = None,
        delegation: PolicyLayer | None = None,
        risk: SecurityPolicy | None = None,
        audit: SecurityAuditLog | None = None,
        tool_risk_lookup: Callable[[str], str] | None = None,
    ) -> None:
        self._base = base or PolicyEngine()
        self._organization = organization
        self._workspace = workspace
        self._delegation = delegation
        self._risk = risk
        self._audit = audit
        #: Server-side risk grading for a tool *name*. Never callable with
        #: caller-supplied data (AUTHZ §6.1): ``ToolRegistry`` is the source.
        self._tool_risk_lookup = tool_risk_lookup
        self._layers = tuple(
            layer
            for layer in (organization, workspace, delegation)
            if layer is not None
        )

    @property
    def floor(self) -> tuple[str, ...]:
        """The floor rule ids in force, surfaced for ``sprout info``."""
        base = self._base
        floor = getattr(base, "floor", None)
        return tuple(floor.rule_ids) if floor is not None else ()

    @property
    def layers(self) -> tuple[PolicyLayer, ...]:
        return self._layers

    # -- assembly ----------------------------------------------------------
    @classmethod
    def from_settings(
        cls,
        security: SecuritySettings,
        *,
        base: PolicyEngineProtocol | None = None,
        audit: SecurityAuditLog | None = None,
        tool_risk_lookup: Callable[[str], str] | None = None,
    ) -> LayeredPolicyEngine:
        """Assemble the engine from ``[security.*]`` configuration."""
        rules = security.rules
        organization_rules: list[PolicyRule] = [
            PolicyRule(
                action="file.read",
                path_glob=f"{prefix}*",
                decision=AccessDecision.DENY,
                id=f"organization:legacy-prefix:{prefix}",
            )
            for prefix in security.organization_deny_prefixes
        ]
        organization = PolicyLayer.from_command_globs(
            "organization",
            tuple(rules.deny) or DEFAULT_ORGANIZATION_DENY,
            decision=AccessDecision.DENY,
            prefix="deny",
        )
        if organization_rules:
            organization = PolicyLayer(
                "organization", (*organization_rules, *organization.rules)
            )
        allow_layer = PolicyLayer.from_command_globs(
            "organization",
            tuple(rules.allow),
            decision=AccessDecision.ALLOW,
            prefix="allow",
        )

        workspace_mapping = dict(rules.workspace)
        for prefix in security.workspace_deny_prefixes:
            workspace_mapping.setdefault(f"file.read:{prefix}*", AccessDecision.DENY.value)
        workspace = (
            PolicyLayer.from_mapping("workspace", workspace_mapping)
            if workspace_mapping
            else None
        )
        delegation = (
            PolicyLayer.from_mapping("delegation", dict(rules.delegation))
            if rules.delegation
            else None
        )
        organization_rules_all = PolicyLayer(
            "organization", (*organization.rules, *allow_layer.rules)
        )

        return cls(
            base or PolicyEngine(),
            organization=organization_rules_all,
            workspace=workspace,
            delegation=delegation,
            risk=SecurityPolicy(allow_medium_risk=security.allow_medium_risk),
            audit=audit,
            tool_risk_lookup=tool_risk_lookup,
        )

    # -- decisions ---------------------------------------------------------
    def decide(self, request: ActionRequest) -> PolicyDecision:
        base_decision = self._base.decide(request)
        effective = base_decision.decision
        matched = list(base_decision.matched_rules)
        reason = base_decision.reason

        for layer in self._layers:
            rule = layer.match(request)
            if rule is None:
                continue
            matched.append(rule.id or f"{layer.name}:<unnamed>")
            if rule.decision is AccessDecision.ALLOW:
                # An operator allow rule pre-approves its pattern; it never
                # widens a deny, sandbox-only, or redacted decision.
                if effective is AccessDecision.REQUIRE_APPROVAL:
                    effective = AccessDecision.ALLOW
                    reason = f"Pre-approved by {rule.id or layer.name}"
                continue
            tightened = self._intersect(effective, rule.decision)
            if tightened is not effective:
                reason = f"Tightened by {rule.id or layer.name}: {rule.decision.value}"
            effective = tightened

        risk_rule = self._risk_check(request)
        if risk_rule is not None:
            matched.extend(risk_rule.matched_rules)
            tightened = self._intersect(effective, risk_rule.decision)
            if tightened is not effective:
                reason = risk_rule.reason
            effective = tightened

        decision = PolicyDecision(
            decision=effective,
            reason=reason or f"Effective policy after {len(self._layers)} layer(s)",
            matched_rules=tuple(matched),
        )
        if self._audit is not None:
            self._audit.record_decision(request, decision)
        return decision

    def _risk_check(self, request: ActionRequest) -> PolicyDecision | None:
        """Apply the tool-risk floor from a *server-side* risk lookup.

        The level used to be read straight out of ``request.arguments``, which
        is caller-supplied — the same self-attestation shape that got
        ``known_command`` removed (AUTHZ §6.1). A tool named in the request is
        now graded through the lookup the runtime wires to the tool registry,
        and an unresolvable name is denied instead of waved through.
        """
        if self._risk is None or self._tool_risk_lookup is None:
            return None
        tool = request.arguments.get("tool_name")
        if not isinstance(tool, str) or not tool:
            return None
        try:
            risk_level = self._tool_risk_lookup(tool)
        except (KeyError, LookupError):
            return PolicyDecision(
                decision=AccessDecision.DENY,
                reason=f"Unknown tool {tool!r} has no risk grade",
                matched_rules=(f"risk:unresolved:{tool}",),
            )
        if not risk_level:
            return PolicyDecision(
                decision=AccessDecision.DENY,
                reason=f"Tool {tool!r} declares no risk level",
                matched_rules=(f"risk:undeclared:{tool}",),
            )
        return self._risk.evaluate(tool=tool, risk_level=risk_level)

    @staticmethod
    def _intersect(left: AccessDecision, right: AccessDecision) -> AccessDecision:
        if AccessDecision.DENY in {left, right}:
            return AccessDecision.DENY
        if AccessDecision.REQUIRE_APPROVAL in {left, right}:
            return AccessDecision.REQUIRE_APPROVAL
        if AccessDecision.SANDBOX_ONLY in {left, right}:
            return AccessDecision.SANDBOX_ONLY
        if AccessDecision.ALLOW_REDACTED in {left, right}:
            return AccessDecision.ALLOW_REDACTED
        return AccessDecision.ALLOW

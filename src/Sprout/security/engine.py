"""Default PolicyEngine for ActionRequest decisions (AUTHZ §1, §3.2).

This is the *base* layer of the matrix. It is deliberately ignorant of
organization, workspace, and delegation policy — those tighten it in
:class:`~Sprout.security.layered_policy.LayeredPolicyEngine` — but it does own
two things nothing may override:

* the **hard floor** (``security/floor.py``), which runs first;
* the **resource-kind matrix**, which now covers writes and deletes too, so a
  sandbox write can no longer overwrite ``.env`` or a private key.
"""

from __future__ import annotations

from Sprout.security.access import (
    AccessDecision,
    ActionRequest,
    ActionType,
    PolicyDecision,
)
from Sprout.security.floor import HardFloor
from Sprout.workspace.models import ResourceKind

#: Kinds whose writes are refuse-outright, mirroring the read rules.
_WRITE_DENIED_KINDS = frozenset({ResourceKind.SECRET, ResourceKind.EXTERNAL})
#: Kinds whose writes must be decided by a human.
_WRITE_APPROVAL_KINDS = frozenset({ResourceKind.SENSITIVE})
#: Kinds that may only be deleted with approval.
_DELETE_APPROVAL_KINDS = frozenset({ResourceKind.DATA, ResourceKind.SENSITIVE})


class PolicyEngine:
    """Applies the default policy matrix; deny by default, floor first."""

    def __init__(self, *, floor: HardFloor | None = None) -> None:
        self._floor = floor or HardFloor()

    @property
    def floor(self) -> HardFloor:
        return self._floor

    def decide(self, request: ActionRequest) -> PolicyDecision:
        floor_decision = self._floor.check(request)
        if floor_decision is not None:
            return floor_decision

        # Skill lifecycle is decided by provenance, not by a resource path
        # (design §8.4). The hard floor above has already run, so a fatal scan
        # can never reach this point.
        if request.action in {ActionType.SKILL_INSTALL, ActionType.SKILL_ENABLE}:
            return _skill_decision(request)

        path = request.resource.path if request.resource is not None else ""
        if request.scope.is_expired():
            return _decision(
                AccessDecision.DENY,
                "DelegationScope expired; treated as no scope",
                "scope:expired",
            )
        if not request.scope.permits(request.action.value, path):
            return _decision(
                AccessDecision.DENY,
                "Action is outside DelegationScope",
                "scope:denied",
            )

        if request.resource is None:
            if request.action in {ActionType.PROCESS_RUN, ActionType.NETWORK_GET}:
                return _decision(AccessDecision.ALLOW, "", "matrix:no-resource")
            return _decision(
                AccessDecision.DENY,
                "Action requires a resource reference",
                "matrix:missing-resource",
            )

        kind = request.resource.kind
        if request.action is ActionType.SECRET_USE:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                "Secret use requires approval",
                "matrix:secret.use",
            )
        if request.action is ActionType.FILE_READ:
            return self._read_decision(kind)
        if request.action is ActionType.FILE_WRITE:
            return self._write_decision(kind)
        if request.action is ActionType.FILE_DELETE:
            return self._delete_decision(kind)
        if request.action is ActionType.PROCESS_RUN:
            # ``auto_run_command`` is derived server-side by CommandRegistry and
            # only ever set for names the operator explicitly opted in. Being
            # merely "recognised" (``allowlisted_command``) is not enough: every
            # build tool on that list executes code the task itself can write.
            if bool(request.arguments.get("auto_run_command", False)):
                return _decision(
                    AccessDecision.ALLOW,
                    "Command is on the operator's auto-run list",
                    "matrix:process.run:auto-run",
                )
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                "Process execution requires approval",
                "matrix:process.run",
            )
        if request.action is ActionType.NETWORK_POST:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                "Network writes require approval",
                "matrix:network.post",
            )
        if request.action is ActionType.NETWORK_GET:
            return _decision(AccessDecision.ALLOW, "", "matrix:network.get")
        if request.action in {ActionType.DB_READ, ActionType.GIT_STATUS, ActionType.GIT_DIFF}:
            return _decision(AccessDecision.ALLOW, "", f"matrix:{request.action.value}")
        if request.action is ActionType.DB_WRITE:
            return _decision(
                AccessDecision.SANDBOX_ONLY,
                "Database writes are sandbox-first",
                "matrix:db.write",
            )
        if request.action in {ActionType.GIT_COMMIT, ActionType.GIT_PUSH}:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                "Git state changes require approval",
                f"matrix:{request.action.value}",
            )
        return _decision(
            AccessDecision.DENY,
            f"No default policy for {request.action.value}",
            f"matrix:unmapped:{request.action.value}",
        )

    @staticmethod
    def _read_decision(kind: ResourceKind) -> PolicyDecision:
        if kind is ResourceKind.SECRET:
            return _decision(
                AccessDecision.DENY, "Secret read is denied", "matrix:file.read:secret"
            )
        if kind is ResourceKind.EXTERNAL:
            return _decision(
                AccessDecision.DENY,
                "Reads outside the workspace boundary are denied",
                "matrix:file.read:external",
            )
        if kind is ResourceKind.SENSITIVE:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                "Sensitive read requires approval",
                "matrix:file.read:sensitive",
            )
        if kind in {
            ResourceKind.PUBLIC,
            ResourceKind.SOURCE,
            ResourceKind.TEST,
            ResourceKind.CONFIG,
            ResourceKind.DOCUMENTATION,
        }:
            return _decision(AccessDecision.ALLOW, "", f"matrix:file.read:{kind.value}")
        if kind is ResourceKind.DATA:
            return _decision(
                AccessDecision.ALLOW_REDACTED,
                "Data read is allowed with redaction",
                "matrix:file.read:data",
            )
        return _decision(
            AccessDecision.DENY,
            f"Unsupported read resource kind: {kind.value}",
            f"matrix:file.read:unsupported:{kind.value}",
        )

    @staticmethod
    def _write_decision(kind: ResourceKind) -> PolicyDecision:
        if kind in _WRITE_DENIED_KINDS:
            return _decision(
                AccessDecision.DENY,
                f"Writes to {kind.value} resources are denied",
                f"matrix:file.write:{kind.value}",
            )
        if kind in _WRITE_APPROVAL_KINDS:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                f"Writes to {kind.value} resources require approval",
                f"matrix:file.write:{kind.value}",
            )
        return _decision(
            AccessDecision.SANDBOX_ONLY,
            "File writes are sandbox-first",
            f"matrix:file.write:{kind.value}",
        )

    @staticmethod
    def _delete_decision(kind: ResourceKind) -> PolicyDecision:
        if kind in _WRITE_DENIED_KINDS:
            return _decision(
                AccessDecision.DENY,
                f"Deleting {kind.value} resources is denied",
                f"matrix:file.delete:{kind.value}",
            )
        if kind in _DELETE_APPROVAL_KINDS:
            return _decision(
                AccessDecision.REQUIRE_APPROVAL,
                f"Deleting {kind.value} resources requires approval",
                f"matrix:file.delete:{kind.value}",
            )
        return _decision(
            AccessDecision.REQUIRE_APPROVAL,
            "File deletion requires approval",
            f"matrix:file.delete:{kind.value}",
        )


#: Sources whose skills are authored inside this project; they install freely.
_FIRST_PARTY_SKILL_SOURCES = frozenset({"local", "project", "evolved"})


def _skill_decision(request: ActionRequest) -> PolicyDecision:
    """Skill lifecycle decisions by provenance (design §8.4).

    First-party skills (authored here) install without a prompt; anything pulled
    from a catalog or the network is approved by a human. The hard floor has
    already run, so a fatal scan never reaches this point.
    """
    source = str(request.arguments.get("source", "")).casefold()
    action = request.action.value
    if source in _FIRST_PARTY_SKILL_SOURCES:
        return _decision(AccessDecision.ALLOW, "", f"matrix:{action}:first-party")
    return _decision(
        AccessDecision.REQUIRE_APPROVAL,
        f"Skill from source {source or 'unknown'!r} requires approval",
        f"matrix:{action}:third-party",
    )


def _decision(decision: AccessDecision, reason: str, rule: str) -> PolicyDecision:
    return PolicyDecision(decision=decision, reason=reason, matched_rules=(rule,))

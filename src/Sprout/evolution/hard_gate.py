"""Hard safety gates for growth candidates."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.artifacts.models import Artifact, ArtifactKind, GrowthCandidate

# Content that would weaken the runtime's own safety boundary is never learnable.
_UNSAFE_PATTERNS: tuple[str, ...] = (
    "bypass",
    "disable policy",
    "ignore approval",
    "skip approval",
    "sudo ",
    "rm -rf",
    "chmod 777",
    "secret value",
    "api_key=",
)

# Metadata keys through which a candidate could ask for broader permissions.
_PERMISSION_KEYS: tuple[str, ...] = (
    "required_permissions",
    "permission_scope",
    "permissions",
    "scope_expansion",
)


@dataclass(frozen=True, slots=True)
class HardGateResult:
    passed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateChecks:
    """External signals the gate treats as blocking failures.

    ``None`` means "not measured yet" and never counts as a pass; only an
    explicit failure blocks the candidate.
    """

    tests_passed: bool | None = None
    regression_free: bool | None = None


class HardGateEvaluator:
    """Rejects candidates that are unsafe, expand permissions, or regress.

    Hard gates are absolute: a higher utility score can never offset them
    (SEMA spec 16.4).
    """

    def evaluate(
        self, candidate: GrowthCandidate, checks: GateChecks | None = None
    ) -> HardGateResult:
        artifact = candidate.artifact
        if artifact is None:
            return HardGateResult(passed=False, reasons=("candidate has no artifact",))

        reasons: list[str] = []
        if not artifact.content.strip():
            reasons.append("artifact content is empty")
        if not candidate.evidence_ids:
            reasons.append("candidate has no evidence")
        if artifact.scope == "global" and len(candidate.evidence_ids) < 3:
            reasons.append("global artifact requires at least 3 evidence references")

        # Runtime core and policy are never auto-grown; tool proposals stay proposals.
        if artifact.kind is ArtifactKind.TOOL_PROPOSAL:
            reasons.append("tool proposals can only be proposed, never published")

        reasons.extend(self._permission_expansion(artifact))
        reasons.extend(self._unsafe_content(artifact))
        reasons.extend(self._external_failures(checks))

        return HardGateResult(passed=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _permission_expansion(artifact: Artifact) -> list[str]:
        reasons: list[str] = []
        metadata = dict(artifact.metadata or {})
        for key in _PERMISSION_KEYS:
            if metadata.get(key):
                reasons.append(f"candidate requests permission expansion via {key}")
        if metadata.get("target") == "runtime_core":
            reasons.append("runtime core cannot be modified by growth")
        return reasons

    @staticmethod
    def _unsafe_content(artifact: Artifact) -> list[str]:
        content = artifact.content.lower()
        hits = [pattern for pattern in _UNSAFE_PATTERNS if pattern in content]
        if hits:
            return [f"artifact content weakens a safety boundary: {', '.join(hits)}"]
        return []

    @staticmethod
    def _external_failures(checks: GateChecks | None) -> list[str]:
        if checks is None:
            return []
        reasons: list[str] = []
        if checks.tests_passed is False:
            reasons.append("key tests failed")
        if checks.regression_free is False:
            reasons.append("critical regression detected")
        return reasons

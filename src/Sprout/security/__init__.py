"""Security layer: risk levels, policy engines, approvals, and secrets.

The layer is organised as one decision path (AUTHZ §1):

``ActionRequest`` -> :class:`LayeredPolicyEngine` (hard floor -> base matrix ->
organization -> workspace -> delegation -> tool-risk floor) -> ``PolicyDecision``
with provenance -> optionally recorded in the tamper-evident
:class:`SecurityAuditLog`.

Brokers never decide anything themselves; they build an ``ActionRequest`` and
obey the returned decision.
"""

from Sprout.security.access import (
    AccessDecision,
    ActionRequest,
    ActionType,
    PolicyDecision,
)
from Sprout.security.approval import (
    ApprovalManager,
    ApprovalMode,
    ApprovalPolicy,
    ApprovalRecord,
    ApprovalStatus,
    ApprovalStore,
)
from Sprout.security.audit import (
    AuditVerification,
    SecurityAuditLog,
    verify_chain,
)
from Sprout.security.commands import CommandRegistry, build_command_registry
from Sprout.security.engine import PolicyEngine
from Sprout.security.floor import DEFAULT_FLOOR_RULES, FloorRule, HardFloor
from Sprout.security.layered_policy import LayeredPolicyEngine, PolicyLayer, PolicyRule
from Sprout.security.net_guard import NetworkGuard, NetworkVerdict
from Sprout.security.policy import Decision, SecurityPolicy
from Sprout.security.protocol import PolicyEngineProtocol
from Sprout.security.redact import RedactionResult, Redactor
from Sprout.security.risk import RiskLevel
from Sprout.security.secret_broker import DEFAULT_ENV_WHITELIST, SecretBroker
from Sprout.security.secrets import (
    PROVIDER_API_KEY_ENV,
    EnvSecretProvider,
    SecretProvider,
    get_secret,
    resolve_api_key,
)

__all__ = [
    "AccessDecision",
    "ActionRequest",
    "ActionType",
    "ApprovalManager",
    "ApprovalMode",
    "ApprovalPolicy",
    "ApprovalRecord",
    "ApprovalStatus",
    "ApprovalStore",
    "AuditVerification",
    "CommandRegistry",
    "DEFAULT_ENV_WHITELIST",
    "DEFAULT_FLOOR_RULES",
    "Decision",
    "EnvSecretProvider",
    "FloorRule",
    "HardFloor",
    "LayeredPolicyEngine",
    "NetworkGuard",
    "NetworkVerdict",
    "PROVIDER_API_KEY_ENV",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyEngineProtocol",
    "PolicyLayer",
    "PolicyRule",
    "RedactionResult",
    "Redactor",
    "RiskLevel",
    "SecretBroker",
    "SecretProvider",
    "SecurityAuditLog",
    "SecurityPolicy",
    "build_command_registry",
    "get_secret",
    "resolve_api_key",
    "verify_chain",
]

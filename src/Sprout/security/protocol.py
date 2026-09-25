"""The single decision protocol every policy engine implements (AUTHZ §1.1).

``PolicyEngine`` (the default matrix), ``LayeredPolicyEngine`` (organization /
workspace / delegation / risk), and any future engine all answer the same
question through :meth:`PolicyEngineProtocol.decide`, so brokers never need to
know which engine they were handed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from Sprout.security.access import ActionRequest, PolicyDecision


@runtime_checkable
class PolicyEngineProtocol(Protocol):
    """One decision entry point for an :class:`ActionRequest`."""

    def decide(self, request: ActionRequest) -> PolicyDecision: ...

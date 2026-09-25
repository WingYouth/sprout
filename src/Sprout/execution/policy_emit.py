"""Publish authorization events from the async broker path (AUTHZ §7.4).

The policy engines are synchronous by design — they must stay usable from
non-async callers and must not depend on the event bus — so the events that
*describe* their verdicts are published here, at the async call sites that
already hold the bus. Every broker calls :func:`emit_policy_decision` right
after ``policy.decide(...)``:

* ``policy.decided`` — one event per verdict, carrying the action, the outcome,
  and the matched rules, so the observations lane can compute the ``policy.decide``
  monitoring metrics from the event stream alone.
* ``auth.scope_expired`` — a second, narrower event when the verdict was driven
  by an expired :class:`~Sprout.task.models.DelegationScope` (``scope:expired``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.events import EventBus
    from Sprout.security.access import ActionRequest, PolicyDecision

#: Rule marker the base engine stamps on a denial caused by an expired scope.
SCOPE_EXPIRED_RULE = "scope:expired"


async def emit_policy_decision(
    events: EventBus | None,
    request: ActionRequest,
    decision: PolicyDecision,
    *,
    correlation_id: str | None = None,
) -> None:
    """Publish ``policy.decided`` and, when applicable, ``auth.scope_expired``.

    Fail-open: an absent bus is a no-op, and bus failures never propagate back
    into the decide path (``EventBus.publish`` already gathers with
    ``return_exceptions=True``).
    """
    if events is None:
        return

    from Sprout.events import AUTH_SCOPE_EXPIRED, POLICY_DECIDED, Event

    await events.publish(
        Event(
            POLICY_DECIDED,
            {
                "action": request.action.value,
                "decision": decision.decision.value,
                "reason": decision.reason,
                "matched_rules": list(decision.matched_rules),
                "task_id": request.task_id,
                "resource": request.resource.path if request.resource is not None else "",
            },
            correlation_id,
        )
    )
    if SCOPE_EXPIRED_RULE in decision.matched_rules:
        await events.publish(
            Event(
                AUTH_SCOPE_EXPIRED,
                {
                    "task_id": request.task_id,
                    "action": request.action.value,
                    "resource": request.resource.path if request.resource is not None else "",
                },
                correlation_id,
            )
        )


__all__ = ["SCOPE_EXPIRED_RULE", "emit_policy_decision"]

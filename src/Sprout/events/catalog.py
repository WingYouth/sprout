"""Canonical event catalog, grouped by runtime domain.

The catalog is intentionally plain data: publishers import the string constants,
while the event bus imports the lane table to register known routes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventDefinition:
    """One named event and its default routing metadata."""

    name: str
    category: str
    lane: str = "audit"
    bus_event: bool = True


# Runtime lifecycle
RUNTIME_STARTED = "runtime.started"
RUNTIME_STOPPED = "runtime.stopped"

# Message flow
MESSAGE_RECEIVED = "message.received"
MESSAGE_SENT = "message.sent"
MESSAGE_PERSISTED = "message.persisted"
SESSION_CREATED = "session.created"

# Agent flow
AGENT_STARTED = "agent.started"
AGENT_COMPLETED = "agent.completed"
AGENT_FAILED = "agent.failed"

# Tool flow
TOOL_EXECUTED = "tool.executed"
TOOL_DENIED = "tool.denied"
FILE_DELETED = "file.deleted"
WORKSPACE_CONSENT_REQUESTED = "workspace.consent.requested"

# Security flow
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
APPROVAL_EXPIRED = "approval.expired"

# Authorization flow
AUTH_ROLES_DISCARDED = "auth.roles_discarded"
AUTH_SELF_ATTESTATION_IGNORED = "auth.self_attestation_ignored"
AUTH_SCOPE_EXPIRED = "auth.scope_expired"
POLICY_DECIDED = "policy.decided"
AUDIT_WRITE_FAILED = "audit.write_failed"

# Skill lifecycle
SKILL_PUBLISHED = "skill.published"

# Growth layer
EVOLUTION_SIGNAL = "evolution.signal"
EVOLUTION_PROPOSAL = "evolution.proposal"
EVOLUTION_PUBLISHED = "evolution.published"

# Intent recognition
INTENT_RECOGNIZED = "intent.recognized"
INTENT_CONVERSATION_REQUESTED = "intent.conversation.requested"
INTENT_TASK_REQUESTED = "intent.task.requested"
INTENT_DELETE_REQUESTED = "intent.delete.requested"
INTENT_WORKSPACE_REQUESTED = "intent.workspace.requested"
INTENT_TOOL_REQUESTED = "intent.tool.requested"
INTENT_APPROVAL_REQUESTED = "intent.approval.requested"
INTENT_MEMORY_REQUESTED = "intent.memory.requested"
INTENT_EVOLUTION_REQUESTED = "intent.evolution.requested"
INTENT_STRATEGY_REQUESTED = "intent.strategy.requested"

# Security audit stream kinds. These are written to the tamper-evident audit
# stream rather than published through EventBus, but they still share the
# canonical event namespace.
AUDIT_POLICY_DECISION = "policy.decision"
AUDIT_APPROVAL_DECISION = "approval.decision"
AUDIT_COMMAND_ALLOWLISTED = "command.allowlisted"
AUDIT_NETWORK_BLOCKED = "network.blocked"
AUDIT_APPROVAL_RESUME_FAILED = "approval.resume_failed"

# Transactional outbox kinds. These are persisted in the conversation database
# and replayed by OutboxWorker, not fanned out by EventBus.
OUTBOX_TURN_INDEXED = "turn.indexed"
OUTBOX_OBSERVATION = "observation"


EVENT_DEFINITIONS: tuple[EventDefinition, ...] = (
    EventDefinition(RUNTIME_STARTED, "runtime_lifecycle", "audit"),
    EventDefinition(RUNTIME_STOPPED, "runtime_lifecycle", "audit"),
    EventDefinition(MESSAGE_RECEIVED, "conversation", "conversation"),
    EventDefinition(MESSAGE_SENT, "conversation", "conversation"),
    EventDefinition(MESSAGE_PERSISTED, "conversation", "conversation"),
    EventDefinition(SESSION_CREATED, "conversation", "conversation"),
    EventDefinition(AGENT_STARTED, "agent", "usage"),
    EventDefinition(AGENT_COMPLETED, "agent", "usage"),
    EventDefinition(AGENT_FAILED, "agent", "usage"),
    EventDefinition(TOOL_EXECUTED, "tools", "usage"),
    EventDefinition(TOOL_DENIED, "tools", "audit"),
    EventDefinition(FILE_DELETED, "files", "audit"),
    EventDefinition(WORKSPACE_CONSENT_REQUESTED, "workspace", "conversation"),
    EventDefinition(APPROVAL_REQUESTED, "approvals", "audit"),
    EventDefinition(APPROVAL_DECIDED, "approvals", "audit"),
    EventDefinition(APPROVAL_EXPIRED, "approvals", "audit"),
    EventDefinition(AUTH_ROLES_DISCARDED, "authorization", "audit"),
    EventDefinition(AUTH_SELF_ATTESTATION_IGNORED, "authorization", "audit"),
    EventDefinition(AUTH_SCOPE_EXPIRED, "authorization", "audit"),
    EventDefinition(POLICY_DECIDED, "authorization", "audit"),
    EventDefinition(AUDIT_WRITE_FAILED, "audit", "audit"),
    EventDefinition(SKILL_PUBLISHED, "skills", "knowledge"),
    EventDefinition(EVOLUTION_SIGNAL, "evolution", "evolution"),
    EventDefinition(EVOLUTION_PROPOSAL, "evolution", "evolution"),
    EventDefinition(EVOLUTION_PUBLISHED, "evolution", "evolution"),
    EventDefinition(INTENT_RECOGNIZED, "intent", "conversation"),
    EventDefinition(INTENT_CONVERSATION_REQUESTED, "intent", "conversation"),
    EventDefinition(INTENT_TASK_REQUESTED, "intent", "conversation"),
    EventDefinition(INTENT_DELETE_REQUESTED, "intent", "conversation"),
    EventDefinition(INTENT_WORKSPACE_REQUESTED, "intent", "conversation"),
    EventDefinition(INTENT_TOOL_REQUESTED, "intent", "audit"),
    EventDefinition(INTENT_APPROVAL_REQUESTED, "intent", "audit"),
    EventDefinition(INTENT_MEMORY_REQUESTED, "intent", "knowledge"),
    EventDefinition(INTENT_EVOLUTION_REQUESTED, "intent", "evolution"),
    EventDefinition(INTENT_STRATEGY_REQUESTED, "intent", "conversation"),
    EventDefinition(AUDIT_POLICY_DECISION, "audit", "audit", bus_event=False),
    EventDefinition(AUDIT_APPROVAL_DECISION, "audit", "audit", bus_event=False),
    EventDefinition(AUDIT_COMMAND_ALLOWLISTED, "audit", "audit", bus_event=False),
    EventDefinition(AUDIT_NETWORK_BLOCKED, "audit", "audit", bus_event=False),
    EventDefinition(AUDIT_APPROVAL_RESUME_FAILED, "audit", "audit", bus_event=False),
    EventDefinition(OUTBOX_TURN_INDEXED, "outbox", "conversation", bus_event=False),
    EventDefinition(OUTBOX_OBSERVATION, "outbox", "audit", bus_event=False),
)

EVENT_REGISTRY: dict[str, EventDefinition] = {
    definition.name: definition for definition in EVENT_DEFINITIONS
}
EVENT_LANES: dict[str, str] = {
    definition.name: definition.lane for definition in EVENT_DEFINITIONS
}
BUS_EVENT_LANES: dict[str, str] = {
    definition.name: definition.lane
    for definition in EVENT_DEFINITIONS
    if definition.bus_event
}

_categories: dict[str, list[EventDefinition]] = defaultdict(list)
for definition in EVENT_DEFINITIONS:
    _categories[definition.category].append(definition)
EVENTS_BY_CATEGORY: dict[str, tuple[EventDefinition, ...]] = {
    category: tuple(definitions) for category, definitions in sorted(_categories.items())
}


def events_for_category(category: str) -> tuple[EventDefinition, ...]:
    """Return the registered events in one category."""

    return EVENTS_BY_CATEGORY.get(category, ())


def event_names(*, bus_only: bool = False) -> tuple[str, ...]:
    """Return all registered event names, optionally limited to EventBus names."""

    definitions = (
        definition for definition in EVENT_DEFINITIONS if definition.bus_event or not bus_only
    )
    return tuple(definition.name for definition in definitions)


__all__ = [
    "AGENT_COMPLETED",
    "AGENT_FAILED",
    "AGENT_STARTED",
    "APPROVAL_DECIDED",
    "APPROVAL_EXPIRED",
    "APPROVAL_REQUESTED",
    "AUDIT_APPROVAL_DECISION",
    "AUDIT_COMMAND_ALLOWLISTED",
    "AUDIT_NETWORK_BLOCKED",
    "AUDIT_POLICY_DECISION",
    "AUDIT_WRITE_FAILED",
    "AUTH_ROLES_DISCARDED",
    "AUTH_SCOPE_EXPIRED",
    "AUTH_SELF_ATTESTATION_IGNORED",
    "BUS_EVENT_LANES",
    "EVENT_DEFINITIONS",
    "EVENT_LANES",
    "EVENT_REGISTRY",
    "EVENTS_BY_CATEGORY",
    "FILE_DELETED",
    "WORKSPACE_CONSENT_REQUESTED",
    "EVOLUTION_PROPOSAL",
    "EVOLUTION_PUBLISHED",
    "EVOLUTION_SIGNAL",
    "EventDefinition",
    "INTENT_APPROVAL_REQUESTED",
    "INTENT_CONVERSATION_REQUESTED",
    "INTENT_DELETE_REQUESTED",
    "INTENT_EVOLUTION_REQUESTED",
    "INTENT_MEMORY_REQUESTED",
    "INTENT_RECOGNIZED",
    "INTENT_TASK_REQUESTED",
    "INTENT_TOOL_REQUESTED",
    "INTENT_WORKSPACE_REQUESTED",
    "MESSAGE_PERSISTED",
    "MESSAGE_RECEIVED",
    "MESSAGE_SENT",
    "OUTBOX_OBSERVATION",
    "OUTBOX_TURN_INDEXED",
    "POLICY_DECIDED",
    "RUNTIME_STARTED",
    "RUNTIME_STOPPED",
    "SESSION_CREATED",
    "SKILL_PUBLISHED",
    "TOOL_DENIED",
    "TOOL_EXECUTED",
    "event_names",
    "events_for_category",
]

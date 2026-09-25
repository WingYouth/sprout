"""Event catalog registration and classification tests."""

from __future__ import annotations

from Sprout.events import (
    EVENT_DEFINITIONS,
    EVENT_LANES,
    EVENTS_BY_CATEGORY,
    OUTBOX_TURN_INDEXED,
    EventBus,
    event_names,
    register_builtin_events,
)
from Sprout.events.catalog import (
    AUDIT_POLICY_DECISION,
    INTENT_RECOGNIZED,
    INTENT_TASK_REQUESTED,
    MESSAGE_RECEIVED,
)


def test_event_catalog_names_are_unique() -> None:
    names = [definition.name for definition in EVENT_DEFINITIONS]

    assert len(names) == len(set(names))
    assert tuple(names) == event_names()


def test_event_catalog_groups_runtime_audit_and_outbox_events() -> None:
    assert MESSAGE_RECEIVED in {event.name for event in EVENTS_BY_CATEGORY["conversation"]}
    assert AUDIT_POLICY_DECISION in {event.name for event in EVENTS_BY_CATEGORY["audit"]}
    assert OUTBOX_TURN_INDEXED in {event.name for event in EVENTS_BY_CATEGORY["outbox"]}
    assert INTENT_RECOGNIZED in {event.name for event in EVENTS_BY_CATEGORY["intent"]}
    assert INTENT_TASK_REQUESTED in {event.name for event in EVENTS_BY_CATEGORY["intent"]}


def test_builtin_registration_covers_the_whole_catalog() -> None:
    bus = register_builtin_events(EventBus())

    assert bus.known_events() == EVENT_LANES

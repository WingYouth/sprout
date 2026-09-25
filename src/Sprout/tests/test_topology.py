"""Topology registry tests: one authority per entity, and no dangling database.

These guard the R0 consolidation. The registry must stay complete: every
entity has exactly one durable authority, derived lanes are only capability
lanes, and every on-disk database has a verdict (active / rehome / legacy),
so an orphan file cannot silently accumulate.
"""

from __future__ import annotations

import pytest

from Sprout.storage import topology
from Sprout.storage.plan import DATA_LAYER, authority_keys
from Sprout.storage.topology import (
    ENTITY_OWNERSHIP,
    STORAGE_DATABASES,
    EntityOwnership,
    authority_lanes,
    classify_database,
    consistency_violations,
    derived_lanes,
    entity_ownership,
    topology_plan,
)

# -- entity registry ---------------------------------------------------------


def test_registry_covers_the_expected_entity_set() -> None:
    entities = [own.entity for own in ENTITY_OWNERSHIP]
    for name in (
        "session",
        "turn",
        "message",
        "attachment",
        "message_task_link",
        "task",
        "approval",
        "runtime_workspace",
        "workspace",
        "execution_run",
        "execution_step",
        "change_set",
        "file_change",
        "validation",
        "execution_node",
        "artifact",
        "change_proposal",
        "knowledge",
        "knowledge_item",
        "capability_note",
        "knowledge_evidence",
        "knowledge_link",
        "event",
        "reflection",
        "trajectory",
        "signal",
        "proposal",
        "memory_fact",
        "user_fact",
        "model_call",
        "tool_usage",
    ):
        assert name in entities, name


def test_every_entity_has_exactly_one_durable_authority() -> None:
    for own in ENTITY_OWNERSHIP:
        assert own.authority in authority_lanes(), own.entity
        # An entity's authority may not be a derived lane.
        assert own.authority not in derived_lanes(), own.entity


def test_derived_lanes_are_capability_or_index_only() -> None:
    for own in ENTITY_OWNERSHIP:
        for lane in own.derived:
            assert lane in derived_lanes(), (own.entity, lane)
            assert lane not in authority_lanes(), (own.entity, lane)


def test_payload_lane_is_only_the_blobstore() -> None:
    for own in ENTITY_OWNERSHIP:
        if own.payload_lane is not None:
            assert own.payload_lane == "blobstore", own.entity


def test_lookup_rejects_unknown_entities() -> None:
    try:
        entity_ownership("nonexistent")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown entity")


# -- database disposition ----------------------------------------------------


def test_every_known_database_has_a_verdict() -> None:
    for db in STORAGE_DATABASES:
        assert db.status in {"active", "rehome", "legacy"}, db.filename
        assert db.action, db.filename


def test_on_disk_set_is_fully_classified() -> None:
    # Every file the old layout may leave behind plus the five new authorities.
    on_disk = {
        "sprout_core.db",
        "sprout_conversation.db",
        "sprout_knowledge.db",
        "sprout_audit.db",
        "sprout_usage.db",
        "sprout_context.db",
        "runtime.db",
        "session.db",
        "sema.db",
        "knowledge.db",
        "observations.db",
        "growth.db",
        "memory.db",
        "herness.db",
        "llm_usage.db",
        "context.db",
    }
    classified = {db.filename: db.status for db in STORAGE_DATABASES}
    for name in on_disk:
        assert name in classified, f"{name} has no disposition"
    # And every registry entry maps to a real planned file (no ghosts).
    assert set(classified) == on_disk


def test_consolidation_targets_six_active_stores() -> None:
    active = [d.filename for d in STORAGE_DATABASES if d.status == "active"]
    assert active == [
        "sprout_core.db",
        "sprout_conversation.db",
        "sprout_knowledge.db",
        "sprout_audit.db",
        "sprout_usage.db",
        "sprout_context.db",
    ]
    rehomed = {d.filename: d.action for d in STORAGE_DATABASES if d.status == "rehome"}
    assert "runtime.db" in rehomed
    assert rehomed["session.db"] == "migrate-to sprout_conversation.db"
    assert rehomed["sema.db"] == "migrate-to sprout_core.db"
    legacy = {d.filename for d in STORAGE_DATABASES if d.status == "legacy"}
    assert legacy == {"herness.db"}


def test_classify_flags_undocumented_files_as_dangling() -> None:
    assert classify_database("sprout_core.db") == "active"
    assert classify_database("runtime.db") == "rehome"
    assert classify_database("growth.db") == "rehome"
    assert classify_database("herness.db") == "legacy"
    assert classify_database("unknown.db") == "dangling"


# -- consistency with the lane plan ------------------------------------------


def test_topology_aligns_with_the_six_lane_plan() -> None:
    # The authority lanes in the entity registry must match the data-layer
    # plan's declared authoritative databases.
    planned_authority = set(authority_keys())
    assert {"sqlite", "jsonl", "blobstore"} <= planned_authority
    topo = topology_plan()
    assert {"entities", "databases"} == set(topo)
    assert len(topo["entities"]) == len(ENTITY_OWNERSHIP)
    assert len(topo["databases"]) == len(STORAGE_DATABASES)


def test_lane_plan_covers_all_six_entries() -> None:
    assert [entry.key for entry in DATA_LAYER] == [
        "sqlite",
        "jsonl",
        "blobstore",
        "redis",
        "milvus",
        "neo4j",
    ]


# -- B1: cross-registry consistency guard ------------------------------------


def test_memory_and_growth_authorities_are_not_rehomed_databases() -> None:
    # memory_fact / user_fact moved to the filesystem layer (memory); signal /
    # proposal moved to sprout_core.db. Neither may still point at a rehome/legacy
    # file, and the disposition of every sqlite authority must be active.
    assert consistency_violations() == []


def test_consistency_guard_reads_a_windows_style_authority_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The basename must come out of either separator spelling.

    The registry renders its authority backend from ``Path.home()``, so on
    Windows the DSN holds backslashes. Splitting on ``/`` alone left the whole
    path in place, no disposition matched, and the guard reported all thirteen
    sqlite entities as dangling — a guard that can never be green on Windows is
    not a guard. This pins the normalisation on every platform.
    """
    windows_style = EntityOwnership(
        "session",
        "sqlite",
        "sqlite:///C:\\Users\\someone\\.sprout\\data\\sprout_conversation.db",
    )
    monkeypatch.setattr(topology, "ENTITY_OWNERSHIP", (windows_style,))

    assert consistency_violations() == []


def test_consistency_guard_still_flags_a_dangling_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must stay able to fail."""
    orphan = EntityOwnership(
        "session",
        "sqlite",
        "sqlite:///C:\\Users\\someone\\.sprout\\data\\nowhere.db",
    )
    monkeypatch.setattr(topology, "ENTITY_OWNERSHIP", (orphan,))

    violations = consistency_violations()

    assert len(violations) == 1
    assert "nowhere.db" in violations[0]


def test_memory_layer_is_a_first_class_authority_lane() -> None:
    assert "memory" in authority_lanes()
    for entity in ("memory_fact", "user_fact"):
        own = entity_ownership(entity)
        assert own.authority == "memory", entity
        assert own.authority not in derived_lanes(), entity


def test_signal_and_proposal_live_in_the_metadata_store() -> None:
    for entity in ("signal", "proposal"):
        own = entity_ownership(entity)
        assert own.authority == "sqlite", entity
        assert own.authority_backend.endswith("sprout_core.db"), entity

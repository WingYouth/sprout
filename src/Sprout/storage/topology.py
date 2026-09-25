"""Data-layer topology: two physical layers, one authority per entity.

Sprout owns its runtime state in ``sprout_*`` databases; user project ontology
lives under ``projects/{project_id}/project_*``. ``sprout_*`` databases may
only hold bridge references into that project layer, never a second authority
for project structure.

This registry maps every data entity to its durable authority and derived
lanes, and classifies every SQLite file that has ever been part of the local
layout. The guard in :func:`consistency_violations` rejects dangling authority
registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SPROUT_DATA = Path.home() / ".sprout" / "data"
_PROJECT_ROOT = _SPROUT_DATA / "projects"


def _sqlite_dsn(filename: str) -> str:
    return f"sqlite:///{_SPROUT_DATA / filename}"


# Derived lanes that may index or cache an authoritative entity.
_DERIVED_LANES = frozenset({"redis", "milvus", "neo4j", "fts"})
# Durable authority lanes. ``memory`` is the filesystem layer (MEMORY.md /
# USER.md), a first-class authority alongside sqlite / jsonl / blobstore.
_AUTHORITY_LANES = frozenset({"sqlite", "jsonl", "blobstore", "memory"})


@dataclass(frozen=True, slots=True)
class EntityOwnership:
    """One data entity: its durable authority and the derived lanes built on it.

    ``payload_lane`` lets an entity split metadata from large bytes -- e.g. an
    artifact keeps a row in the metadata store but its payload body goes to the
    blobstore.
    """

    entity: str
    authority: str  # one of _AUTHORITY_LANES
    authority_backend: str  # e.g. "sqlite:////<home>/.sprout/data/sprout_core.db"
    derived: tuple[str, ...] = ()  # subset of _DERIVED_LANES
    payload_lane: str | None = None  # blobstore when the body lives out-of-line

    def to_dict(self) -> dict[str, object]:
        return {
            "entity": self.entity,
            "authority": self.authority,
            "authority_backend": self.authority_backend,
            "derived": list(self.derived),
            "payload_lane": self.payload_lane,
        }


#: The complete entity -> authority / derived registry.
ENTITY_OWNERSHIP: tuple[EntityOwnership, ...] = (
    EntityOwnership(
        "session",
        "sqlite",
        _sqlite_dsn("sprout_conversation.db"),
        ("redis", "milvus", "neo4j", "fts"),
    ),
    EntityOwnership(
        "turn",
        "sqlite",
        _sqlite_dsn("sprout_conversation.db"),
        ("milvus", "neo4j", "fts"),
    ),
    EntityOwnership(
        "message",
        "sqlite",
        _sqlite_dsn("sprout_conversation.db"),
        ("milvus", "fts"),
    ),
    EntityOwnership(
        "attachment",
        "sqlite",
        _sqlite_dsn("sprout_conversation.db"),
        payload_lane="blobstore",
    ),
    EntityOwnership("message_task_link", "sqlite", _sqlite_dsn("sprout_conversation.db")),
    EntityOwnership("task", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("approval", "sqlite", _sqlite_dsn("sprout_audit.db")),
    EntityOwnership("runtime_workspace", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("workspace", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("execution_run", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("execution_step", "sqlite", _sqlite_dsn("sprout_core.db")),
    EntityOwnership("change_set", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership(
        "file_change",
        "sqlite",
        _sqlite_dsn("sprout_core.db"),
        payload_lane="blobstore",
    ),
    EntityOwnership("validation", "sqlite", _sqlite_dsn("sprout_core.db")),
    EntityOwnership(
        "artifact",
        "sqlite",
        _sqlite_dsn("sprout_core.db"),
        ("neo4j",),
        payload_lane="blobstore",
    ),
    EntityOwnership("execution_node", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("change_proposal", "sqlite", _sqlite_dsn("sprout_core.db"), ("neo4j",)),
    EntityOwnership("knowledge", "sqlite", _sqlite_dsn("sprout_knowledge.db"), ("milvus",)),
    EntityOwnership("knowledge_item", "sqlite", _sqlite_dsn("sprout_knowledge.db"), ("milvus",)),
    EntityOwnership("capability_note", "sqlite", _sqlite_dsn("sprout_knowledge.db")),
    EntityOwnership("knowledge_evidence", "sqlite", _sqlite_dsn("sprout_knowledge.db")),
    EntityOwnership("knowledge_link", "sqlite", _sqlite_dsn("sprout_knowledge.db")),
    EntityOwnership("event", "sqlite", _sqlite_dsn("sprout_audit.db")),
    EntityOwnership("reflection", "sqlite", _sqlite_dsn("sprout_audit.db")),
    EntityOwnership("model_call", "sqlite", _sqlite_dsn("sprout_usage.db")),
    EntityOwnership("tool_usage", "sqlite", _sqlite_dsn("sprout_usage.db")),
    EntityOwnership(
        "trajectory",
        "jsonl",
        (_SPROUT_DATA / "sprout_trajectory").as_posix() + "/",
    ),
    EntityOwnership("signal", "sqlite", _sqlite_dsn("sprout_core.db"), (),),
    EntityOwnership("proposal", "sqlite", _sqlite_dsn("sprout_core.db"), (),),
    EntityOwnership("memory_fact", "memory", "memory://MEMORY.md", ("fts",)),
    EntityOwnership("user_fact", "memory", "memory://USER.md", ("fts",)),
)


@dataclass(frozen=True, slots=True)
class DatabaseDisposition:
    """Verdict for one SQLite file found in ``~/.sprout/data/``."""

    filename: str
    status: str  # active | rehome | legacy
    owns: str
    action: str  # keep | migrate-to … | merge-into … | delete

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "status": self.status,
            "owns": self.owns,
            "action": self.action,
        }


#: Disposition of every known on-disk database, including the legacy files the
#: previous six-database layout left behind.
STORAGE_DATABASES: tuple[DatabaseDisposition, ...] = (
    DatabaseDisposition(
        "sprout_core.db",
        "active",
        "runtime coordination: workspaces, tasks, runs, steps, changes, artifacts",
        "keep",
    ),
    DatabaseDisposition(
        "sprout_conversation.db",
        "active",
        "conversation: sessions, messages, attachments, task links",
        "keep",
    ),
    DatabaseDisposition(
        "sprout_knowledge.db",
        "active",
        "Sprout operating knowledge, memory facts, capability notes",
        "keep",
    ),
    DatabaseDisposition(
        "sprout_audit.db",
        "active",
        "approvals, security events, web requests, operation logs",
        "keep",
    ),
    DatabaseDisposition(
        "sprout_usage.db",
        "active",
        "model calls and tool usage",
        "keep",
    ),
    DatabaseDisposition(
        "sprout_context.db",
        "active",
        "derived context snapshots and FTS index",
        "keep",
    ),
    DatabaseDisposition(
        "runtime.db", "rehome", "legacy operational store", "migrate-to sprout_audit.db"
    ),
    DatabaseDisposition(
        "session.db", "rehome", "legacy session store", "migrate-to sprout_conversation.db"
    ),
    DatabaseDisposition(
        "sema.db", "rehome", "legacy metadata store", "migrate-to sprout_core.db"
    ),
    DatabaseDisposition(
        "knowledge.db", "rehome", "legacy knowledge store", "migrate-to sprout_knowledge.db"
    ),
    DatabaseDisposition(
        "observations.db",
        "rehome",
        "legacy observation store",
        "migrate-to sprout_audit.db",
    ),
    DatabaseDisposition(
        "growth.db", "rehome", "legacy growth store", "migrate-to sprout_core.db"
    ),
    DatabaseDisposition(
        "memory.db",
        "rehome",
        "legacy memory FTS store",
        "merge-into sprout_conversation.db FTS",
    ),
    DatabaseDisposition("herness.db", "legacy", "old metadata store", "delete"),
    DatabaseDisposition(
        "llm_usage.db",
        "rehome",
        "legacy standalone usage store",
        "migrate-to sprout_usage.db",
    ),
    DatabaseDisposition(
        "context.db",
        "rehome",
        "legacy context snapshot store",
        "migrate-to derived context index",
    ),
)

_DISPOSITION_BY_NAME: dict[str, str] = {d.filename: d.status for d in STORAGE_DATABASES}


def entity_ownership(entity: str) -> EntityOwnership:
    for own in ENTITY_OWNERSHIP:
        if own.entity == entity:
            return own
    raise KeyError(f"Unknown entity: {entity!r}")


def classify_database(filename: str) -> str:
    """Disposition for a database filename; ``dangling`` when undocumented."""
    return _DISPOSITION_BY_NAME.get(filename, "dangling")


def topology_plan() -> dict[str, list[dict[str, object]]]:
    """The registry as data: entities and on-disk dispositions."""
    return {
        "entities": [own.to_dict() for own in ENTITY_OWNERSHIP],
        "databases": [d.to_dict() for d in STORAGE_DATABASES],
    }


def authority_lanes() -> frozenset[str]:
    return _AUTHORITY_LANES


def derived_lanes() -> frozenset[str]:
    return _DERIVED_LANES


def consistency_violations() -> list[str]:
    """Cross-registry consistency guard.

    The entity registry names each entity's durable authority; the on-disk
    disposition table names each database's verdict. A database that an entity
    still claims as authority must never be flagged ``rehome`` / ``legacy``.
    """
    disposition = {d.filename: d.status for d in STORAGE_DATABASES}
    violations: list[str] = []
    for own in ENTITY_OWNERSHIP:
        if own.authority != "sqlite":
            continue
        filename = own.authority_backend.replace("\\", "/").rsplit("/", 1)[-1]
        status = disposition.get(filename)
        if status is None:
            violations.append(
                f"entity {own.entity!r} claims {filename!r} as authority but "
                "that database has no disposition"
            )
        elif status != "active":
            violations.append(
                f"entity {own.entity!r} claims {filename!r} as authority but "
                f"the database is flagged {status!r}"
            )
    return violations

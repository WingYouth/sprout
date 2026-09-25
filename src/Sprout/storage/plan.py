"""The data-layer plan: which layer owns what, and who may call it.

One entry per physical lane in the Sprout runtime + user project architecture
(SQLite, JSONL, BlobStore, Redis, Milvus, Neo4j). The plan is data, not prose,
so tooling can print it (``sprout storage plan``), tests can assert it stays
complete, and the wiring code has one place to look for "where does this
belong?".

Two rules the plan encodes:

1. **One authority per entity.** Exactly one database is the durable source of
   truth for a piece of data; everything else is a derived index, cache, or
   evidence log that can be rebuilt.
2. **Calls go through a contract.** Runtime components never reach a database
   directly; they call a ``Sprout.storage.contracts`` protocol, and the DSN
   picks the backend.

See ``STORAGE_AND_MEMORY.md`` for the full written proposal (it merges the two
earlier drafts, ``DATA_LAYER.md`` and ``MEMORY_AND_CONTEXT.md``, now archived
under ``.workbuddy/legacy/docs-20260921/``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.config.settings import StorageSettings


@dataclass(frozen=True, slots=True)
class DataLayerEntry:
    """One database in the data layer.

    ``authority`` means the store can hold durable, non-rebuildable data — true
    for SQLite, JSONL, and BlobStore, false for cache/vector/graph stores,
    which are always derived.
    """

    key: str
    scheme: str
    lane: str
    authority: bool
    responsibility: str
    owns: tuple[str, ...]
    contract: str
    backend: str
    retention: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "scheme": self.scheme,
            "lane": self.lane,
            "authority": self.authority,
            "responsibility": self.responsibility,
            "owns": list(self.owns),
            "contract": self.contract,
            "backend": self.backend,
            "retention": self.retention,
        }


#: The six databases, in the order the architecture diagram lists them.
DATA_LAYER: tuple[DataLayerEntry, ...] = (
    DataLayerEntry(
        key="sqlite",
        scheme="sqlite://",
        lane="authority",
        authority=True,
        responsibility="Sprout runtime and user-project authorities",
        owns=(
            "runtime coordination (sprout_core.db)",
            "conversation (sprout_conversation.db)",
            "runtime knowledge (sprout_knowledge.db)",
            "approvals/audit (sprout_audit.db)",
            "model/tool usage (sprout_usage.db)",
            "project ontology (projects/{project_id}/project_*.db)",
            "tasks",
            "approvals",
            "workspaces",
            "artifacts (metadata)",
            "change proposals",
            "execution nodes",
            "knowledge items",
            "events",
            "reflections",
        ),
        contract="OperationalStore / MetadataStore / KnowledgeStore / "
        "ObservationStore / SessionStore",
        backend="SqlSessionStore, SqliteOperationalStore, SqliteMetadataStore, "
        "SqliteKnowledgeStore, SqliteObservationStore, project SQLite stores",
        retention="Archive cold sessions and tasks; no TTL",
    ),
    DataLayerEntry(
        key="jsonl",
        scheme="jsonl://",
        lane="evidence",
        authority=True,
        responsibility="Audit trail, trajectory, replay, rollback evidence",
        owns=(
            "runtime traces (sprout_trajectory/*.jsonl)",
            "project traces (projects/{project_id}/trajectory/*.jsonl)",
            "session event streams",
        ),
        contract="TrajectoryRecorder / SessionStore",
        backend="JsonlTrajectoryRecorder, JsonlSessionStore",
        retention="Rotate by day or size, then compact",
    ),
    DataLayerEntry(
        key="blobstore",
        scheme="blobstore://",
        lane="authority",
        authority=True,
        responsibility="Files, attachments, oversized payloads, exports",
        owns=(
            "message attachments",
            "oversized message/turn bodies",
            "artifact payloads",
            "media and exports",
        ),
        contract="BlobStore",
        backend="FileBlobStore, MemoryBlobStore, BlobSessionStore",
        retention="Content-addressed; garbage-collect unreferenced blobs",
    ),
    DataLayerEntry(
        key="redis",
        scheme="redis://",
        lane="capability",
        authority=False,
        responsibility="Hot cache, task queue, locks, rate limits, live status",
        owns=(
            "sprout:* hot sessions and run status",
            "project:{id}:* project hot path",
            "retrieval and model response cache",
            "task queue",
            "short-lived status flags",
        ),
        contract="CacheStore (queue and lock contracts pending)",
        backend="MemoryCacheStore, RedisCacheStore; RedisSessionStore as the "
        "hot session lane",
        retention="TTL on every key; trim lists to a fixed length",
    ),
    DataLayerEntry(
        key="milvus",
        scheme="milvus://",
        lane="capability",
        authority=False,
        responsibility="Embeddings: semantic search, Q&A, context recall",
        owns=(
            "sprout_vec_messages and sprout_vec_tasks",
            "sprout_vec_knowledge_chunks",
            "project_{id}_vec_* user-project vectors",
            "skill and artifact embeddings",
        ),
        contract="VectorStore",
        backend="MemoryVectorStore, MilvusVectorStore, MilvusSessionStore",
        retention="Rebuildable; cascade-delete vectors with their source rows",
    ),
    DataLayerEntry(
        key="neo4j",
        scheme="neo4j://",
        lane="capability",
        authority=False,
        responsibility="Graph relations: project, entity, capability, dependency",
        owns=(
            "Sprout Task/Run/ChangeSet/Knowledge relations",
            "UserProject/UserComponent/UserSymbol/UserTable relations",
            "skill capability graph",
        ),
        contract="GraphStore (pending)",
        backend="Neo4jSessionStore (reserved)",
        retention="Rebuildable projection; cascade-delete with source entities",
    ),
)


def authority_keys() -> tuple[str, ...]:
    """Keys of the databases that hold durable, non-rebuildable data."""
    return tuple(entry.key for entry in DATA_LAYER if entry.authority)


def entry_for(key: str) -> DataLayerEntry:
    for entry in DATA_LAYER:
        if entry.key == key:
            return entry
    raise KeyError(f"Unknown data-layer key: {key!r}")


def resolve_dsns(settings: StorageSettings) -> dict[str, str]:
    """Map each data-layer key to the DSN or path configured for it."""
    return {
        "sqlite": (
            f"core={settings.core} | conversation={settings.conversation} | "
            f"knowledge={settings.knowledge} | audit={settings.audit} | "
            f"usage={settings.usage} | projects={settings.project_root}"
        ),
        "jsonl": f"{settings.trajectory_dir}/",
        "blobstore": f"{settings.blobs_dir}/",
        "redis": settings.cache,
        "milvus": settings.vectors,
        "neo4j": settings.graph,
    }


def data_layer_plan(settings: StorageSettings) -> list[dict[str, object]]:
    """The plan joined with the configured DSNs, ready for CLI or JSON output."""
    dsns = resolve_dsns(settings)
    return [{**entry.to_dict(), "dsn": dsns.get(entry.key, "")} for entry in DATA_LAYER]

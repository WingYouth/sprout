"""StorageBundle: one object bundling every store, plus the local-first factory."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.rootstock import SessionStore, create_session_store
from Sprout.storage.contracts.blobs import BlobStore
from Sprout.storage.contracts.cache import CacheStore
from Sprout.storage.contracts.knowledge import KnowledgeStore
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.storage.contracts.observations import ObservationStore
from Sprout.storage.contracts.operational import OperationalStore
from Sprout.storage.contracts.skills import SkillStore
from Sprout.storage.contracts.vectors import VectorStore
from Sprout.storage.local.filesystem.blobs import FileBlobStore
from Sprout.storage.local.memory import (
    MemoryBlobStore,
    MemoryCacheStore,
    MemoryKnowledgeStore,
    MemoryObservationStore,
    MemoryOperationalStore,
    MemorySkillStore,
)
from Sprout.storage.local.memory.vectors import MemoryVectorStore
from Sprout.storage.local.sqlite.knowledge import open_knowledge_store
from Sprout.storage.local.sqlite.metadata import open_metadata_store
from Sprout.storage.local.sqlite.observations import open_observation_store
from Sprout.storage.local.sqlite.operational import open_operational_store
from Sprout.storage.local.sqlite.skills import open_skill_store

logger = logging.getLogger("sprout.storage.bundle")

if TYPE_CHECKING:
    from Sprout.config.settings import MemorySettings, StorageSettings
    from Sprout.memory.contract import MemoryStore, SessionSearch
    from Sprout.storage.contracts.context import ContextStore
    from Sprout.storage.contracts.graph import GraphStore
    from Sprout.storage.lanes import SixLaneFanout
    from Sprout.storage.local.sqlite.memory_index import SqliteMemoryIndex


@dataclass(slots=True)
class StorageBundle:
    operational: OperationalStore
    knowledge: KnowledgeStore
    skills: SkillStore | None = None
    sessions: SessionStore | None = None
    metadata: MetadataStore | None = None
    observations: ObservationStore | None = None
    vectors: VectorStore | None = None
    cache: CacheStore | None = None
    blobs: BlobStore | None = None
    memory: MemoryStore | None = None
    session_search: SessionSearch | None = None
    graph: GraphStore | None = None
    context: ContextStore | None = None
    memory_index: SqliteMemoryIndex | None = None
    lanes: SixLaneFanout | None = None
    usage: Any | None = None

    @classmethod
    def in_memory(cls) -> StorageBundle:
        from Sprout.memory.backends.memory_store import MemoryMemoryStore
        from Sprout.memory.backends.session_search import MemorySessionSearch
        from Sprout.rootstock.backends.memory_store import MemorySessionStore

        return cls(
            operational=MemoryOperationalStore(),
            knowledge=MemoryKnowledgeStore(),
            skills=MemorySkillStore(),
            sessions=MemorySessionStore(),
            observations=MemoryObservationStore(),
            cache=MemoryCacheStore(),
            blobs=MemoryBlobStore(),
            memory=MemoryMemoryStore(),
            session_search=MemorySessionSearch(),
            vectors=MemoryVectorStore(),
        )

    def session_store(self) -> SessionStore:
        """The session layer store; the operational store is the fallback."""
        return self.sessions if self.sessions is not None else self.operational

    async def close(self) -> None:
        """Close every store that owns a resource (SQLite connections)."""
        for store in (
            self.operational,
            self.knowledge,
            self.skills,
            self.sessions,
            self.metadata,
            self.observations,
            self.vectors,
            self.memory,
            self.session_search,
            self.graph,
            self.context,
            self.lanes,
            self.usage,
        ):
            close = getattr(store, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass

    async def delete_session_cascade(self, session_id: str) -> dict[str, int]:
        """Delete a session and cascade to its derived data (M10).

        Returns a per-store count: ``turns`` dropped, ``fts`` rows unindexed,
        ``blobs`` removed. User memory and trajectory are intentionally kept.

        Blob collection happens **before** anything is deleted: offloaded bodies
        are content-addressed (a bare hash filename with no session component),
        so once the rows that name them are gone there is no way back — and the
        contract has no garbage collector to catch what this misses.
        """
        report: dict[str, int] = {"turns": 0, "fts": 0, "blobs": 0}
        session_store = self.session_store()

        blob_uris: list[str] = []
        if self.blobs is not None:
            blob_uris.extend(await self._session_blob_uris(session_store, session_id))
            blob_uris.extend(await self._context_blob_uris(session_id))

        if hasattr(session_store, "delete_session"):
            report["turns"] = await session_store.delete_session(session_id)
        if self.session_search is not None:
            report["fts"] = await self.session_search.unindex_session(session_id)
        if self.memory is not None and hasattr(self.memory, "remove_session_fact"):
            await self.memory.remove_session_fact(session_id, substring="")

        for uri in dict.fromkeys(blob_uris):
            try:
                if await self.blobs.delete(uri):
                    report["blobs"] += 1
            except (KeyError, OSError):
                pass
        return report

    async def _session_blob_uris(self, session_store: Any, session_id: str) -> list[str]:
        """Blob URIs named by the session's turns.

        A backend without ``session_blob_uris`` cannot be asked what it holds, so
        this says so in the log instead of returning an empty list that reads
        like "this session had no blobs" — the silence that let every offloaded
        body leak behind a green test suite.
        """
        collect = getattr(session_store, "session_blob_uris", None)
        if not callable(collect):
            logger.warning(
                "Session store %s cannot report blob URIs; any offloaded bodies "
                "it holds for session %s cannot be reclaimed",
                type(session_store).__name__,
                session_id,
            )
            return []
        return list(await collect(session_id))

    async def _context_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs named by this session's context snapshots.

        The context lane offloads bodies over ``BLOB_THRESHOLD_BYTES`` of its own
        (see ``SixLaneFanout.persist_context``). Those URIs live on
        ``ContextRecord.blob_uri``, not on any turn, so the turn scan never saw
        them and they leaked the same way.
        """
        if self.context is None:
            return []
        list_records = getattr(self.context, "list_records", None)
        if not callable(list_records):
            return []
        try:
            records = await list_records(session_id, limit=10**6)
        except Exception as exc:  # noqa: BLE001 - cascade must still delete the session
            logger.warning(
                "Could not read context snapshots for session %s during cascade "
                "cleanup: %s: %s",
                session_id,
                type(exc).__name__,
                exc,
            )
            return []
        return [record.blob_uri for record in records if record.blob_uri]


def _parse_dsn(dsn: str) -> tuple[str, str | None]:
    """Split ``sqlite:////<home>/.sprout/data/sprout_core.db`` into its scheme/path."""
    scheme, _, rest = dsn.partition("://")
    if not scheme:
        raise ValueError(f"Invalid storage DSN: {dsn!r}")
    if scheme == "memory":
        return "memory", None
    if scheme == "jsonl" and rest.startswith("/"):
        return scheme, rest
    return scheme, rest.removeprefix("/") or None


def _discover_session_search(sessions: SessionStore | None) -> SessionSearch | None:
    """Find the SqliteDatabase behind a session store and wrap it as FTS5."""
    if sessions is None:
        return None
    db = getattr(sessions, "_db", None)
    if db is None:
        return None
    try:
        from Sprout.memory.backends.session_search import SqliteSessionSearch

        return SqliteSessionSearch(db)
    except Exception:  # noqa: BLE001
        return None


def create_storage(
    settings: StorageSettings,
    *,
    pragmas: Any = None,
    memory_settings: MemorySettings | None = None,
    sessions: SessionStore | None = None,
    memory_store: MemoryStore | None = None,
    session_search: SessionSearch | None = None,
) -> StorageBundle:
    """Assemble the StorageBundle from settings.

    ``sqlite:///`` DSNs reserve a database file and create its schema on open;
    ``memory://`` selects the in-memory implementation. The session layer is
    assembled by :mod:`Sprout.rootstock`, which also accepts ``jsonl:///``,
    ``blobstore:///``, and the reserved ``milvus://``/``neo4j://``/``redis://``
    schemes. ``pragmas`` tunes every SQLite backend opened by this bundle.

    Memory is a *layer* (filesystem-backed ``MEMORY.md``/``USER.md``); pass
    ``memory_settings`` to wire the file-system store under
    ``memory_settings.home``; pass ``memory_store`` to inject a
    test/ephemeral backend. The session search backend (FTS5) is wired
    automatically when ``sessions`` exposes the underlying
    :class:`SqliteDatabase`.
    """
    if sessions is None:
        sessions = create_session_store(settings.session, pragmas)
    if session_search is None:
        session_search = _discover_session_search(sessions)
    if memory_store is None and memory_settings is not None and memory_settings.enabled:
        from Sprout.memory.backends.file_system import FileSystemMemoryStore

        memory_store = FileSystemMemoryStore(memory_settings.home)

    op_scheme, op_path = _parse_dsn(settings.operational)
    if op_scheme == "memory":
        operational: OperationalStore = MemoryOperationalStore()
    elif op_scheme == "sqlite":
        assert op_path is not None
        operational = open_operational_store(op_path, pragmas)
    else:
        raise ValueError(f"Unsupported operational DSN: {settings.operational!r}")

    # The skill registry shares the operational (audit) authority, so "who
    # approved this skill" is a JOIN away (§10.2).
    skills: SkillStore
    if op_scheme == "memory":
        skills = MemorySkillStore()
    else:
        assert op_path is not None
        skills = open_skill_store(op_path, pragmas)

    kn_scheme, kn_path = _parse_dsn(settings.knowledge)
    if kn_scheme == "memory":
        knowledge: KnowledgeStore = MemoryKnowledgeStore()
    elif kn_scheme == "sqlite":
        assert kn_path is not None
        knowledge = open_knowledge_store(kn_path, pragmas)
    else:
        raise ValueError(f"Unsupported knowledge DSN: {settings.knowledge!r}")

    metadata: MetadataStore | None = None
    if settings.metadata:
        md_scheme, md_path = _parse_dsn(settings.metadata)
        if md_scheme == "memory":
            metadata = None
        elif md_scheme == "sqlite":
            assert md_path is not None
            metadata = open_metadata_store(md_path, pragmas)
        else:
            raise ValueError(f"Unsupported metadata DSN: {settings.metadata!r}")

    observations: ObservationStore | None = None
    if settings.observations.enabled:
        ob_scheme, ob_path = _parse_dsn(settings.observations.dsn)
        if ob_scheme == "memory":
            observations = MemoryObservationStore()
        elif ob_scheme == "sqlite":
            assert ob_path is not None
            observations = open_observation_store(ob_path, pragmas)
        else:
            raise ValueError(
                f"Unsupported observations DSN: {settings.observations.dsn!r}"
            )

    cache: CacheStore | None = None
    if settings.cache == "none":
        cache = None
    elif settings.cache == "memory" or settings.cache == "memory://":
        cache = MemoryCacheStore()
    elif settings.cache.startswith("redis://"):
        from Sprout.storage.local.redis.cache import RedisCacheStore

        cache = RedisCacheStore(settings.cache)
    else:
        raise ValueError(f"Unsupported cache DSN: {settings.cache!r}")

    vectors: VectorStore | None = None
    if settings.vectors == "memory" or settings.vectors == "memory://":
        vectors = MemoryVectorStore()
    elif settings.vectors.startswith("milvus://"):
        from Sprout.storage.local.milvus.vectors import MilvusVectorStore

        vectors = MilvusVectorStore(settings.vectors)
    elif settings.vectors == "none":
        vectors = None
    else:
        raise ValueError(f"Unsupported vectors DSN: {settings.vectors!r}")

    graph = None
    if settings.graph.startswith("neo4j://"):
        from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore

        graph = Neo4jSessionStore(settings.graph)

    context_store = None
    ctx_scheme, ctx_rest = _parse_dsn(settings.context)
    if ctx_scheme == "sqlite":
        from Sprout.storage.local.sqlite.context import SqliteContextStore
        from Sprout.storage.local.sqlite.driver import SqliteDatabase

        assert ctx_rest is not None
        context_store = SqliteContextStore(SqliteDatabase.open(ctx_rest, pragmas))
    elif ctx_scheme == "jsonl":
        from Sprout.storage.local.filesystem.context import JsonlContextStore

        context_store = JsonlContextStore(
            ctx_rest
            or (Path.home() / ".sprout" / "data" / "context").as_posix()
        )

    memory_index = None
    session_db = getattr(sessions, "_db", None)
    if session_db is not None:
        from Sprout.storage.local.sqlite.memory_index import SqliteMemoryIndex

        memory_index = SqliteMemoryIndex(session_db)

    usage = None
    usage_scheme, usage_path = _parse_dsn(settings.usage)
    if usage_scheme == "sqlite":
        from Sprout.llm.usage import LLMUsageRecorder

        assert usage_path is not None
        usage = LLMUsageRecorder(usage_path)
    elif usage_scheme not in {"memory", "none"}:
        raise ValueError(f"Unsupported usage DSN: {settings.usage!r}")

    blobs = FileBlobStore(settings.blobs_dir)
    lanes = None
    redis_lane = None
    wants_fanout = (
        graph is not None
        or cache is not None and settings.cache.startswith("redis://")
        or vectors is not None and settings.vectors.startswith("milvus://")
        or context_store is not None
    )
    if wants_fanout:
        from Sprout.rootstock.backends.redis_store import RedisSessionStore
        from Sprout.storage.lanes import SixLaneFanout

        if settings.cache.startswith("redis://"):
            redis_lane = RedisSessionStore(settings.cache)
        lanes = SixLaneFanout(
            sessions,
            redis=redis_lane,
            graph=graph,
            vectors=vectors,
            fts=session_search,
            blobs=blobs,
            context_store=context_store,
            memory_index=memory_index,
            cache=cache,
        )
        sessions = lanes
        if memory_store is not None:
            from Sprout.storage.lanes import MirroredMemoryStore

            memory_store = MirroredMemoryStore(memory_store, lanes)

    return StorageBundle(
        operational=operational,
        knowledge=knowledge,
        skills=skills,
        sessions=sessions,
        metadata=metadata,
        observations=observations,
        cache=cache,
        blobs=blobs,
        memory=memory_store,
        vectors=vectors,
        session_search=session_search,
        graph=graph,
        context=context_store,
        memory_index=memory_index,
        lanes=lanes,
        usage=usage,
    )


async def storage_status(bundle: StorageBundle) -> dict[str, Any]:
    """Public service used by ``sprout storage status``; never raw SQL."""
    from Sprout.storage.local.sqlite.driver import detect_sqlite_capabilities

    session_store = bundle.session_store()
    operational: dict[str, Any] = {
        "sessions": await session_store.count_sessions(),
        "turns": await session_store.count_turns(),
    }
    list_tasks = getattr(bundle.operational, "list_tasks", None)
    if callable(list_tasks):
        operational["tasks"] = len(await list_tasks())
    list_approvals = getattr(bundle.operational, "list_approvals", None)
    if callable(list_approvals):
        operational["approvals"] = len(await list_approvals())
    status: dict[str, Any] = {
        "operational": operational,
        "knowledge": await bundle.knowledge.count(),
        "sqlite": _as_dict(detect_sqlite_capabilities()),
    }
    status["core"] = {"tasks": operational.get("tasks", 0)}
    status["audit"] = {"approvals": operational.get("approvals", 0)}
    if bundle.observations is not None:
        status["events"] = await bundle.observations.count_events()
    if bundle.blobs is not None:
        status["blobs"] = await bundle.blobs.count()
    if bundle.vectors is not None:
        status["vectors"] = await bundle.vectors.count()
    if bundle.sessions is not None:
        status["session_layer"] = {
            "backend": type(bundle.sessions).__name__,
            "sessions": await bundle.sessions.count_sessions(),
            "turns": await bundle.sessions.count_turns(),
        }
        status["conversation"] = status["session_layer"]
    if bundle.memory is not None:
        status["memory"] = {
            "backend": type(bundle.memory).__name__,
            "facts": await bundle.memory.count_facts()
            if hasattr(bundle.memory, "count_facts")
            else None,
        }
    if bundle.usage is not None:
        status["usage"] = bundle.usage.summary()
    if bundle.session_search is not None:
        status["session_search"] = {
            "backend": type(bundle.session_search).__name__,
            "tokenizer": getattr(bundle.session_search, "tokenizer", None),
        }
    return status


def _as_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {
        f.name: getattr(obj, f.name)
        for f in getattr(obj, "__dataclass_fields__", {}).values()
    }

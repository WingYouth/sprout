"""Six-lane diagnostics: the implementation behind ``sprout storage check``.

The CLI and the generated Docker stack both run this; the
``~/.sprout/docker/six_lane_probe.py`` shim is a
thin shim over :func:`check_lanes`, so "which databases, and verified how" is
defined exactly once.

Two properties are deliberate and easy to lose in a refactor:

* **The write goes through the production path.** The bundle is assembled with
  ``create_storage`` exactly the way the runtime assembles it, so a green run
  says the real fan-out works — not that a test double does.
* **The read-back never reuses the contract objects.** Every lane is read with its
  own native client (``sqlite3`` on the file, Redis, Milvus, Neo4j, the blob
  directory, the JSONL log). That is the whole point: ``SixLaneFanout`` *logs* a
  lane failure instead of raising, so an unreachable Milvus is indistinguishable
  from an empty one unless the lane is inspected directly.

The check is *topology aware*. The Docker profile points all four derived lanes at
services, but a laptop profile legitimately sets them to in-process doubles
(``memory`` / ``none``). A lane with no external backend has no native client to
read back with, so it is skipped and **reported as skipped** — never silently
counted as verified.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Sprout.memory.models import SessionFact
from Sprout.session.models import Session, Turn
from Sprout.storage.bundle import create_storage
from Sprout.storage.contracts.context import ContextRecord
from Sprout.storage.contracts.vectors import SESSION_TURNS
from Sprout.storage.lanes import CONTEXT_SNAPSHOTS_NS, MEMORY_FACTS_NS
from Sprout.storage.local.sqlite.driver import SqlitePragmas

# Exit statuses. The Docker stack maps them onto "did the proof pass", so they
# are part of the contract rather than decoration.
STATUS_OK = 0
STATUS_LANE_FAILURE = 1
STATUS_NO_FANOUT = 2
STATUS_SCHEMA_CONFLICT = 3

# A dedicated probe session: the check resets it (and its cascade) before writing,
# so running it on every `up` stays idempotent.
SESSION_ID = "six-lane-check"
LEGACY_SESSION_ID = "docker-six-lane"
USER_ID = "u-probe"
SNAPSHOT_HASH = "sixlanecafe"
TURN_TEXT = "six-lane check: remember the blue cluster"
FACT_KEY = "deploy"
FACT_VALUE = "blue cluster"
# The blob lane only engages above the fan-out threshold (64 KiB).
BIG_TEXT = "the model saw the blue cluster fact\n" * 3000

# Milvus fixes the embedding width when a collection is created, so a stale
# collection from an earlier run rejects every write.
MILVUS_COLLECTIONS = (
    "sprout_vec_messages",
    "sprout_vec_knowledge_chunks",
    "sprout_vec_context_snapshots",
)

MILVUS_SCHEME = "milvus://"
REDIS_SCHEME = "redis://"
NEO4J_SCHEME = "neo4j://"
JSONL_SCHEME = "jsonl://"


def _pragmas(settings: Any) -> SqlitePragmas:
    """Mirror ``runtime/factory.py`` so SQLite is opened the same way."""
    cfg = settings.sqlite
    return SqlitePragmas(
        busy_timeout_ms=cfg.busy_timeout_ms,
        synchronous=cfg.synchronous,
        wal_autocheckpoint=cfg.wal_autocheckpoint,
        mmap_size=cfg.mmap_size,
        readers=cfg.readers,
    )


def _neo4j_auth():
    from neo4j import Auth

    return Auth("basic", "neo4j", "sprout123")


def _sqlite_path(dsn: str) -> Path | None:
    """Resolve a ``sqlite:///`` DSN the way the storage parsers do.

    Both ``_parse_dsn`` (storage/bundle.py) and ``_split_dsn``
    (rootstock/backends/__init__.py) strip exactly one leading slash, so the
    result is relative to the process working directory.
    """
    prefix = "sqlite://"
    if not dsn.startswith(prefix):
        return None
    rest = dsn[len(prefix) :]
    if rest.startswith("/"):
        rest = rest[1:]
    return Path(rest)


def _http(uri: str) -> str:
    """``milvus://host:19530`` -> ``http://host:19530`` for the raw client."""
    return uri.replace("milvus://", "http://", 1)


def schema_conflicts(client: Any, expected_dim: int) -> list[str]:
    """Collections whose embedding width cannot accept today's vectors.

    Report this up front rather than letting every vector write fail silently: a
    lane failure is logged, not raised, so the symptom would otherwise be "Milvus
    is empty" with no explanation.
    """
    conflicts: list[str] = []
    for name in MILVUS_COLLECTIONS:
        if not client.has_collection(name):
            continue
        fields = client.describe_collection(name).get("fields", []) or []
        dim = None
        for entry in fields:
            if entry.get("name") == "embedding":
                dim = (entry.get("params") or {}).get("dim")
        if dim is not None and int(dim) != expected_dim:
            conflicts.append(f"{name}: embedding dim {dim}, expected {expected_dim}")
    return conflicts


@dataclass(frozen=True)
class Lane:
    """One lane's verdict: what was written, and what its own client saw."""

    name: str
    wrote: str
    saw: str
    ok: bool


@dataclass
class LaneReport:
    """Structured outcome of a six-lane run. Deliberately does no printing.

    Rendering belongs to the caller: the CLI colours it through ``cli.ui``, the
    Docker shim writes plain text.
    """

    title: str
    # "wrote" for the check (what was written before reading it back), "detail"
    # for initialisation (what was created). Rendering follows the verb.
    primary_label: str = "wrote"
    lanes: list[Lane] = field(default_factory=list)
    context: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    lane_errors: list[str] = field(default_factory=list)
    status: int = STATUS_OK

    def add(self, name: str, wrote: str, saw: str, ok: bool) -> None:
        self.lanes.append(Lane(name=name, wrote=wrote, saw=saw, ok=ok))

    def skip(self, name: str, reason: str) -> None:
        """Record a lane that has no external backend to read back with."""
        self.skipped.append(name)
        self.notes.append(f"skipped {name}: {reason}")

    def note(self, message: str) -> None:
        self.notes.append(message)

    def set(self, key: str, value: Any) -> None:
        self.context.append((key, str(value)))

    @property
    def ok(self) -> bool:
        return all(lane.ok for lane in self.lanes)

    def plain(self) -> str:
        """Plain-text rendering, for the Docker shim and for logs."""
        width = max((len(lane.name) for lane in self.lanes), default=0)
        lines = ["", "=" * 96, self.title, "=" * 96]
        for key, value in self.context:
            lines.append(f"{key:<12}: {value}")
        lines.append("-" * 96)
        for lane in self.lanes:
            lines.append(
                f"[{'ok' if lane.ok else 'FAIL':>4}] {lane.name:<{width}}"
                f"  {self.primary_label}: {lane.wrote}"
            )
            if lane.saw:
                lines.append(f"{'':>6} {lane.saw}")
        lines.append("-" * 96)
        for note in self.notes:
            lines.append(f"  {note}")
        lines.append(f"checked        : {len(self.lanes)} lane(s)")
        lines.append(f"lane errors    : {self.lane_errors or 'none'}")
        lines.append("=" * 96)
        return "\n".join(lines)


# -- read-back helpers -------------------------------------------------------
# Each one reads a lane with that lane's own client and records a verdict. The
# caller turns any exception into a FAILED lane, because an unreachable service
# *is* the finding — the whole point is to look at the lane directly instead of
# trusting the fan-out's log.


async def _read_sqlite(storage: Any, report: LaneReport) -> None:
    db = _sqlite_path(storage.session) or Path("sprout_conversation.db")
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        turns = conn.execute(
            "SELECT count(*) FROM turns WHERE session_id = ?", (SESSION_ID,)
        ).fetchone()[0]
        fts = conn.execute(
            "SELECT count(*) FROM turns_fts WHERE session_id = ?", (SESSION_ID,)
        ).fetchone()[0]
        facts = conn.execute(
            "SELECT count(*) FROM memory_fts WHERE owner = ?", (SESSION_ID,)
        ).fetchone()[0]
    report.add(
        "SQLite (authority)",
        f"{db.name} → 2 turns, 1 fact",
        f"turns={turns} turns_fts={fts} memory_fts={facts}",
        turns == 2 and fts >= 2 and facts >= 1,
    )


async def _read_jsonl(storage: Any, report: LaneReport) -> None:
    if not storage.context.startswith(JSONL_SCHEME):
        report.skip(
            "JSONL (evidence)",
            f"the context lane is {storage.context!r}, not a jsonl:// store",
        )
        return
    log = Path(storage.context.removeprefix(JSONL_SCHEME)) / f"{SESSION_ID}.jsonl"
    records = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hashes = [record.get("snapshot_hash") for record in records]
    report.add(
        "JSONL (evidence)",
        f"{log} → 1 record appended",
        f"records={len(records)} snapshot_hash={hashes}",
        SNAPSHOT_HASH in hashes,
    )


async def _read_blob(storage: Any, bundle: Any, stored: Any, report: LaneReport) -> None:
    media = Path(storage.blobs_dir)
    blobs = sorted(p.name for p in media.iterdir() if p.is_file())
    body_ok = False
    if stored.blob_uri:
        body_ok = await bundle.blobs.get(stored.blob_uri) == BIG_TEXT.encode("utf-8")
    report.add(
        "BlobStore (objects)",
        f"{len(BIG_TEXT.encode('utf-8'))} B body beyond the 64 KiB threshold",
        f"blob_uri={stored.blob_uri} files={blobs} read_back={body_ok}",
        bool(stored.blob_uri) and body_ok,
    )


async def _read_redis(storage: Any, report: LaneReport) -> None:
    if not storage.cache.startswith(REDIS_SCHEME):
        report.skip("Redis (hot path)", f"the cache lane is {storage.cache!r}")
        return
    import redis

    client = redis.Redis.from_url(storage.cache, decode_responses=True)
    try:
        hot = client.exists(f"sprout:session:{SESSION_ID}")
        cached = client.get(f"sprout:context:{SESSION_ID}")
        hot_turns = client.lrange(f"sprout:session:{SESSION_ID}:turns", 0, -1)
    finally:
        client.close()
    report.add(
        "Redis (hot path)",
        f"{storage.cache} → session hash + turn list + context cache",
        f"session={hot} turns={len(hot_turns)} cached_hash="
        f"{json.loads(cached)['hash'] if cached else None}",
        hot == 1
        and len(hot_turns) >= 2
        and bool(cached)
        and json.loads(cached)["hash"] == SNAPSHOT_HASH,
    )


async def _read_milvus(storage: Any, report: LaneReport) -> None:
    if not storage.vectors.startswith(MILVUS_SCHEME):
        report.skip("Milvus (vectors)", f"the vectors lane is {storage.vectors!r}")
        return
    from pymilvus import MilvusClient

    milvus = MilvusClient(uri=_http(storage.vectors))
    counts: dict[str, int] = {}
    try:
        for namespace in (SESSION_TURNS, MEMORY_FACTS_NS, CONTEXT_SNAPSHOTS_NS):
            collection = f"sprout_vec_{namespace}"
            try:
                milvus.load_collection(collection)
                counts[collection] = int(
                    milvus.get_collection_stats(collection).get("row_count", 0)
                )
            except Exception as exc:  # noqa: BLE001 - report, do not crash
                counts[collection] = -1
                report.note(f"milvus {collection}: {type(exc).__name__}: {exc}")
    finally:
        milvus.close()
    report.add(
        "Milvus (vectors)",
        f"{storage.vectors} → turn / fact / context vectors",
        f"row counts {counts} (cumulative across runs; drop the collections to reset)",
        all(count >= 1 for count in counts.values()),
    )


async def _read_neo4j(storage: Any, report: LaneReport) -> None:
    if not storage.graph.startswith(NEO4J_SCHEME):
        report.skip("Neo4j (graph)", f"the graph lane is {storage.graph!r}")
        return
    from neo4j import GraphDatabase

    # The store strips the userinfo before handing the URI to the 6.x driver; do
    # the same here and keep the credentials in auth=.
    host = storage.graph.split("@", 1)[-1].removeprefix(NEO4J_SCHEME)
    driver = GraphDatabase.driver(f"bolt://{host}", auth=_neo4j_auth())
    try:
        with driver.session() as graph_session:
            turns_n = graph_session.run(
                "MATCH (t:Turn {session_id: $sid}) RETURN count(t) AS n", sid=SESSION_ID
            ).single()["n"]
            facts_n = graph_session.run(
                "MATCH (f:MemoryFact {owner: $owner}) RETURN count(f) AS n",
                owner=SESSION_ID,
            ).single()["n"]
            snapshots_n = graph_session.run(
                "MATCH (c:ContextSnapshot {hash: $hash}) RETURN count(c) AS n",
                hash=SNAPSHOT_HASH,
            ).single()["n"]
            linked = graph_session.run(
                "MATCH (:Session {id: $sid})-[:HAS_TURN]->(t:Turn) RETURN count(t) AS n",
                sid=SESSION_ID,
            ).single()["n"]
    finally:
        driver.close()
    report.add(
        "Neo4j (graph)",
        f"{storage.graph} → session / turn / fact / snapshot nodes",
        f"turns={turns_n} (linked {linked}) facts={facts_n} snapshots={snapshots_n}",
        turns_n >= 2 and linked >= 2 and facts_n >= 1 and snapshots_n >= 1,
    )


async def check_lanes(
    settings: Any,
    progress: Callable[[str, bool], None] | None = None,
) -> LaneReport:
    """Write once through the bundle, then read every lane back natively.

    Returns a :class:`LaneReport` whose ``status`` is one of ``STATUS_*``. The
    write is preceded by a reset of the probe session, so repeated runs do not
    accumulate rows in the lanes that support deletion.
    """
    storage = settings.storage
    report = LaneReport(title="SIX LANES CHECK")
    report.set("cwd", Path.cwd())
    report.set("session", storage.session)
    report.set("cache", storage.cache)
    report.set("vectors", storage.vectors)
    report.set("graph", storage.graph)
    report.set("context", storage.context)
    report.set("blobs_dir", storage.blobs_dir)

    try:
        bundle = create_storage(
            storage, pragmas=_pragmas(settings), memory_settings=settings.memory
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        report.add("storage bundle", "assembly failed", str(exc), False)
        report.lane_errors = [str(exc)]
        report.status = STATUS_LANE_FAILURE
        return report
    try:
        if bundle.lanes is None:
            report.note(
                "no six-lane fan-out: the configured DSNs do not request the "
                "derived lanes (cache / vectors / graph / context), so there is "
                "nothing to prove."
            )
            report.status = STATUS_NO_FANOUT
            return report

        # -- pre-flight: a stale Milvus schema would fail every vector write ---
        expected_dim = getattr(getattr(bundle.lanes, "embed", None), "dim", None)
        if expected_dim and storage.vectors.startswith(MILVUS_SCHEME):
            try:
                from pymilvus import MilvusClient

                milvus = MilvusClient(uri=_http(storage.vectors))
                try:
                    conflicts = schema_conflicts(milvus, int(expected_dim))
                finally:
                    milvus.close()
                if conflicts:
                    for line in conflicts:
                        report.note(f"milvus schema conflict — {line}")
                    report.note(
                        "derived lane only, safe to drop: "
                        "~/.sprout/docker/ ./bootstrap.ps1 -Clean, then re-run"
                    )
                    report.status = STATUS_SCHEMA_CONFLICT
                    return report
            except Exception as exc:  # noqa: BLE001 - unreachable Milvus is reported later
                report.note(
                    f"milvus preflight skipped: {type(exc).__name__}: {exc}"
                )

        # -- reset: keeps the check idempotent, so it can run on every `up` ----
        dropped = await bundle.delete_session_cascade(SESSION_ID)
        report.note(f"reset: dropped {dropped}")
        # The pre-CLI probe wrote under a different session id; clear it so the
        # check does not leave two probe sessions behind.
        if LEGACY_SESSION_ID != SESSION_ID:
            await bundle.delete_session_cascade(LEGACY_SESSION_ID)

        # -- the write: one session, two turns, one fact, one context snapshot --
        await bundle.sessions.save_session(
            Session(id=SESSION_ID, user_id=USER_ID, metadata={"channel": "probe"})
        )
        await bundle.sessions.append_turn(Turn(SESSION_ID, "user", TURN_TEXT))
        await bundle.sessions.append_turn(Turn(SESSION_ID, "assistant", "noted"))

        if bundle.memory is None:
            report.note("memory layer is not wired")
            report.status = STATUS_NO_FANOUT
            return report
        rejected = await bundle.memory.add_session_fact(
            SessionFact(session_id=SESSION_ID, key=FACT_KEY, value=FACT_VALUE),
            char_limit=settings.memory.session_char_limit,
        )
        if rejected is not None:
            report.note(f"memory fact rejected: {rejected}")
            report.status = STATUS_LANE_FAILURE
            return report

        stored = await bundle.lanes.persist_context(
            ContextRecord(
                session_id=SESSION_ID,
                snapshot_hash=SNAPSHOT_HASH,
                text=BIG_TEXT,
                turn_seq=2,
                token_estimate=1234,
            )
        )

        # -- the read-back: every lane, through its own client -----------------
        reads: tuple[tuple[str, Any], ...] = (
            ("SQLite (authority)", _read_sqlite(storage, report)),
            ("JSONL (evidence)", _read_jsonl(storage, report)),
            ("BlobStore (objects)", _read_blob(storage, bundle, stored, report)),
            ("Redis (hot path)", _read_redis(storage, report)),
            ("Milvus (vectors)", _read_milvus(storage, report)),
            ("Neo4j (graph)", _read_neo4j(storage, report)),
        )
        for name, read in reads:
            ok = True
            try:
                await read
            except Exception as exc:  # noqa: BLE001 - a dead lane is the finding
                ok = False
                report.add(name, "—", f"{type(exc).__name__}: {exc}", False)
            if progress is not None:
                progress(name, ok)

        report.lane_errors = list(bundle.lanes.last_errors)
        report.status = (
            STATUS_OK if report.ok and not report.lane_errors else STATUS_LANE_FAILURE
        )
        return report
    finally:
        await bundle.close()


# -- initialisation ----------------------------------------------------------
# The other half of the job, and the `init` verb in the generated
# ``~/.sprout/docker/bootstrap.*`` stack: create
# every configured lane in an empty, usable state and write no business data.
# Idempotent (IF NOT EXISTS at every layer), so it can run on every start.
#
# Like the check it is topology aware: a lane on an in-process backend has
# nothing to create or contact, so it is skipped and reported as skipped.
#
# A configuration with no derived lanes still *succeeds* - the authority lanes
# were created exactly as asked, so the check's exit 2 ("nothing to prove")
# would be the wrong answer here.


async def _init_sqlite_row(storage: Any, report: LaneReport) -> None:
    dsns = [
        storage.operational,
        storage.knowledge,
        storage.metadata,
        storage.session,
        storage.observations.dsn,
        storage.usage,
    ]
    files: dict[str, Path] = {}
    tables = 0
    missing: list[str] = []
    for dsn in dsns:
        path = _sqlite_path(dsn)
        if path is None:
            continue
        if not path.exists():
            missing.append(str(path))
            continue
        files[str(path.resolve())] = path
    for path in files.values():
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables += conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchone()[0]
    file_names = sorted(path.name for path in files.values())
    report.add(
        "SQLite (authority)",
        f"{len(files)} databases, {tables} tables — {' '.join(file_names)}",
        "",
        not missing and bool(files),
    )


async def _init_jsonl_row(storage: Any, report: LaneReport) -> None:
    if not storage.context.startswith(JSONL_SCHEME):
        report.skip(
            "JSONL (evidence)",
            f"the context lane is {storage.context!r}, not a jsonl:// store",
        )
        return
    directory = Path(storage.context.removeprefix(JSONL_SCHEME))
    directory.mkdir(parents=True, exist_ok=True)
    report.add("JSONL (evidence)", f"{directory}/ ready", "", directory.is_dir())


async def _init_blob_row(storage: Any, bundle: Any, report: LaneReport) -> None:
    media = Path(storage.blobs_dir)
    media.mkdir(parents=True, exist_ok=True)
    report.add(
        "BlobStore (objects)",
        f"{media}/ ready",
        "",
        media.is_dir() and bundle.blobs is not None,
    )


async def _init_redis_row(storage: Any, report: LaneReport) -> None:
    if not storage.cache.startswith(REDIS_SCHEME):
        report.skip("Redis (hot path)", f"the cache lane is {storage.cache!r}")
        return
    import redis

    client = redis.Redis.from_url(storage.cache, decode_responses=True)
    try:
        pong = client.ping()
    finally:
        client.close()
    report.add("Redis (hot path)", f"{storage.cache} → {pong}", "", bool(pong))


async def _init_milvus_row(storage: Any, lanes: Any, report: LaneReport) -> None:
    if not storage.vectors.startswith(MILVUS_SCHEME):
        report.skip("Milvus (vectors)", f"the vectors lane is {storage.vectors!r}")
        return
    from pymilvus import MilvusClient

    vectors = getattr(lanes, "vectors", None)
    if vectors is None:
        report.add("Milvus (vectors)", "the vector lane is not wired", "", False)
        return
    dim = getattr(getattr(lanes, "embed", None), "dim", None)
    # `count` on an absent namespace creates the collection and its schema, which
    # keeps this on public API instead of the store's private helpers.
    rows = {
        f"sprout_vec_{namespace}": await vectors.count(namespace=namespace)
        for namespace in (SESSION_TURNS, MEMORY_FACTS_NS, CONTEXT_SNAPSHOTS_NS)
    }
    widths: dict[str, Any] = {}
    raw = MilvusClient(uri=_http(storage.vectors))
    try:
        for name in rows:
            if not raw.has_collection(name):
                continue
            for entry in raw.describe_collection(name).get("fields", []) or []:
                if entry.get("name") == "embedding":
                    widths[name] = (entry.get("params") or {}).get("dim")
    finally:
        raw.close()
    ok = len(widths) == len(MILVUS_COLLECTIONS) and all(
        int(width) == int(dim) for width in widths.values() if width is not None
    )
    report.add(
        "Milvus (vectors)", f"{len(rows)} collections at dim={dim}, rows={rows}", "", ok
    )


async def _init_neo4j_row(storage: Any, lanes: Any, report: LaneReport) -> None:
    if not storage.graph.startswith(NEO4J_SCHEME):
        report.skip("Neo4j (graph)", f"the graph lane is {storage.graph!r}")
        return
    from neo4j import GraphDatabase

    # A read triggers the store's connect path, which runs the
    # CREATE CONSTRAINT ... IF NOT EXISTS statements.
    sessions = await lanes.graph.count_sessions()
    host = storage.graph.split("@", 1)[-1].removeprefix(NEO4J_SCHEME)
    driver = GraphDatabase.driver(f"bolt://{host}", auth=_neo4j_auth())
    try:
        with driver.session() as graph_session:
            names = [
                record["name"]
                for record in graph_session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            ]
    finally:
        driver.close()
    report.add(
        "Neo4j (graph)",
        f"{storage.graph} → sessions={sessions}, constraints={len(names)} {names}",
        "",
        len(names) >= 1,
    )


async def init_lanes(
    settings: Any,
    progress: Callable[[str, bool], None] | None = None,
) -> LaneReport:
    """Materialise every configured lane empty, writing no business data.

    Returns a :class:`LaneReport`; ``status`` is ``STATUS_LANE_FAILURE`` only when
    a lane that was actually configured could not be created.
    """
    storage = settings.storage
    report = LaneReport(title="SIX LANES INITIALISED", primary_label="detail")
    report.set("cwd", Path.cwd())
    report.set("session", storage.session)
    report.set("cache", storage.cache)
    report.set("vectors", storage.vectors)
    report.set("graph", storage.graph)
    report.set("context", storage.context)
    report.set("blobs_dir", storage.blobs_dir)

    try:
        bundle = create_storage(
            storage, pragmas=_pragmas(settings), memory_settings=settings.memory
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        report.add("storage bundle", "assembly failed", str(exc), False)
        report.lane_errors = [str(exc)]
        report.status = STATUS_LANE_FAILURE
        return report
    try:
        # The authority lanes always exist; create_storage already ran their DDL.
        authority_ok = True
        authority: tuple[tuple[str, Any], ...] = (
            ("SQLite (authority)", _init_sqlite_row(storage, report)),
            ("JSONL (evidence)", _init_jsonl_row(storage, report)),
            ("BlobStore (objects)", _init_blob_row(storage, bundle, report)),
        )
        for name, run in authority:
            ok = True
            try:
                await run
            except Exception as exc:  # noqa: BLE001 - a broken lane is the finding
                ok = False
                authority_ok = False
                report.add(name, f"{type(exc).__name__}: {exc}", "", False)
            if progress is not None:
                progress(name, ok)

        if bundle.lanes is None:
            report.note(
                "no derived lanes configured (cache / vectors / graph / context), "
                "so only the authority lanes were created."
            )
            report.status = STATUS_OK if authority_ok else STATUS_LANE_FAILURE
            return report

        derived_ok = True
        derived: tuple[tuple[str, Any], ...] = (
            ("Redis (hot path)", _init_redis_row(storage, report)),
            ("Milvus (vectors)", _init_milvus_row(storage, bundle.lanes, report)),
            ("Neo4j (graph)", _init_neo4j_row(storage, bundle.lanes, report)),
        )
        for name, run in derived:
            ok = True
            try:
                await run
            except Exception as exc:  # noqa: BLE001 - a broken lane is the finding
                ok = False
                derived_ok = False
                report.add(name, f"{type(exc).__name__}: {exc}", "", False)
            if progress is not None:
                progress(name, ok)

        report.lane_errors = list(bundle.lanes.last_errors)
        if not derived_ok:
            report.note(
                "derived lane(s) are unavailable; local authorities are initialised "
                "and the runtime can start without them."
            )
        report.status = STATUS_OK if authority_ok else STATUS_LANE_FAILURE
        return report
    finally:
        await bundle.close()

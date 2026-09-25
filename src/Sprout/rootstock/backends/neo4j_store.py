"""Neo4j session backend: the graph lane behind the SessionStore protocol.

``(:Session)-[:HAS_TURN]->(:Turn)`` gives traversal-based recall — full
conversation chains, branching turns, and cross-session relationships. The
store also implements the :class:`~Sprout.storage.contracts.graph.GraphStore`
contract, so the six-lane fan-out can project memory facts and context
snapshots into the same graph without a second connection. Requires the
``neo4j`` driver and a reachable server (``neo4j://host:7687``; user:pass
userinfo in the DSN is honored).
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlparse

from Sprout.rootstock.contract import blob_uris_in
from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.session.models import Session, Turn

# Schema assertions applied on first write. Each entry is a uniqueness
# constraint the adapter installs (Neo4j 5 ``CREATE CONSTRAINT`` syntax).
CONSTRAINTS: tuple[str, ...] = (
    "CREATE CONSTRAINT session_id_unique IF NOT EXISTS "
    "FOR (s:Session) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT turn_id_unique IF NOT EXISTS "
    "FOR (t:Turn) REQUIRE t.turn_id IS UNIQUE",
    "CREATE CONSTRAINT fact_key_unique IF NOT EXISTS "
    "FOR (f:MemoryFact) REQUIRE f.fact_key IS UNIQUE",
)

# Cypher template for linking a new turn to its session.
MERGE_TURN = (
    "MERGE (s:Session {id: $session_id}) "
    "MERGE (t:Turn {turn_id: $turn_id}) "
    "SET t.session_id = $session_id, t.seq = $seq, t.role = $role, "
    "t.content = $content, t.preview = $preview, t.created_at = $created_at, "
    "t.metadata_json = $metadata_json "
    "MERGE (s)-[:HAS_TURN]->(t)"
)

# How many characters of a turn's body to embed inline on the (:Turn) node so
# graph-only callers can preview a turn without touching the source store.
CONTENT_PREVIEW_CHARS = 240

_MAX_SEQ_CYPHER = (
    "MATCH (s:Session {id: $session_id})-[:HAS_TURN]->(t:Turn) "
    "RETURN coalesce(max(t.seq), 0) AS highest"
)


def _require_neo4j(dsn: str) -> None:
    if importlib.util.find_spec("neo4j") is None:
        raise RootstockUnavailableError(
            "The neo4j session backend requires the 'neo4j' package. "
            f"Install it (e.g. `uv add neo4j`) and set [storage] session = "
            f'"{dsn}".'
        )


def _auth_from_dsn(dsn: str):
    parsed = urlparse(dsn)
    if parsed.username is None:
        from neo4j import Auth

        return Auth("basic", "neo4j", "sprout123")
    password = unquote(parsed.password) if parsed.password else ""
    from neo4j import Auth

    return Auth("basic", unquote(parsed.username), password)


def _clean_uri(dsn: str) -> str:
    """Strip ``user:pass@`` userinfo — the driver rejects it in URIs.

    Credentials travel via the ``auth=`` argument instead; this keeps
    ``neo4j://user:pass@host:7687`` DSNs working across driver versions.
    """
    parsed = urlparse(dsn)
    scheme = "bolt" if parsed.scheme == "neo4j" else parsed.scheme
    if parsed.username is None:
        return parsed._replace(scheme=scheme).geturl()
    netloc = parsed.netloc.split("@", 1)[-1]
    return parsed._replace(scheme=scheme, netloc=netloc).geturl()


class Neo4jSessionStore:
    """Sessions, turns, and lane projections in one labeled property graph."""

    backend_name = "neo4j"

    def __init__(self, dsn: str) -> None:
        _require_neo4j(dsn)
        from neo4j import AsyncGraphDatabase

        self.dsn = dsn
        self._driver = AsyncGraphDatabase.driver(
            _clean_uri(dsn), auth=_auth_from_dsn(dsn)
        )
        self._constraints_ready = False
        self._seq_cache: dict[str, int] = {}

    async def close(self) -> None:
        await self._driver.close()

    async def _ensure_constraints(self) -> None:
        if self._constraints_ready:
            return
        async with self._driver.session(database="neo4j") as session:
            for cypher in CONSTRAINTS:
                await session.run(cypher)
        self._constraints_ready = True

    async def _run(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run one Cypher statement and return its records as dicts."""
        await self._ensure_constraints()
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(cypher, params or {})
            return [dict(record) for record in await result.data()]

    async def _next_seq(self, session_id: str) -> int:
        if session_id in self._seq_cache:
            self._seq_cache[session_id] += 1
            return self._seq_cache[session_id]
        records = await self._run(
            _MAX_SEQ_CYPHER, {"session_id": session_id}
        )
        highest = int(records[0]["highest"]) if records else 0
        self._seq_cache[session_id] = highest + 1
        return highest + 1

    # -- SessionStore protocol -----------------------------------------------

    async def get_session(self, session_id: str) -> Session | None:
        records = await self._run(
            "MATCH (s:Session {id: $id}) "
            "RETURN s.user_id AS user_id, s.created_at AS created_at, "
            "s.metadata_json AS metadata_json",
            {"id": session_id},
        )
        if not records:
            return None
        row = records[0]
        return Session(
            id=session_id,
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    async def save_session(self, session: Session) -> None:
        await self._run(
            "MERGE (s:Session {id: $id}) "
            "SET s.user_id = $user_id, s.created_at = $created_at, "
            "s.metadata_json = $metadata_json",
            {
                "id": session.id,
                "user_id": session.user_id,
                "created_at": session.created_at.isoformat(),
                "metadata_json": json.dumps(
                    session.metadata, ensure_ascii=False, default=str
                ),
            },
        )

    async def append_turn(self, turn: Turn) -> None:
        # ``turn.seq`` is honored when nonzero: the six-lane fan-out passes the
        # authority-assigned sequence so the graph lane mirrors it exactly.
        if turn.seq > 0:
            seq = turn.seq
            self._seq_cache[turn.session_id] = seq
        else:
            seq = await self._next_seq(turn.session_id)
        await self._run(
            MERGE_TURN,
            {
                "session_id": turn.session_id,
                "turn_id": turn.id,
                "seq": seq,
                "role": turn.role,
                "content": turn.content,
                "preview": turn.content[:CONTENT_PREVIEW_CHARS],
                "created_at": turn.created_at.isoformat(),
                "metadata_json": json.dumps(
                    turn.metadata or {}, ensure_ascii=False, default=str
                ),
            },
        )

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        records = await self._run(
            "MATCH (:Session {id: $id})-[:HAS_TURN]->(t:Turn) "
            "RETURN t.turn_id AS turn_id, t.session_id AS session_id, t.seq AS seq, "
            "t.role AS role, t.content AS content, t.created_at AS created_at, "
            "t.metadata_json AS metadata_json "
            "ORDER BY t.seq DESC LIMIT $limit",
            {"id": session_id, "limit": limit},
        )
        turns = [self._record_to_turn(row) for row in records]
        turns.reverse()
        return turns

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> list[Turn]:
        records = await self._run(
            "MATCH (:Session {id: $id})-[:HAS_TURN]->(t:Turn) "
            "WHERE t.seq < $seq "
            "RETURN t.turn_id AS turn_id, t.session_id AS session_id, t.seq AS seq, "
            "t.role AS role, t.content AS content, t.created_at AS created_at, "
            "t.metadata_json AS metadata_json "
            "ORDER BY t.seq ASC LIMIT $limit",
            {"id": session_id, "seq": seq, "limit": limit},
        )
        return [self._record_to_turn(row) for row in records]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(
            await self.turns_before(session_id, seq=10**12, limit=10**6)
        )

    async def delete_session(self, session_id: str) -> int:
        records = await self._run(
            "MATCH (:Session {id: $id})-[:HAS_TURN]->(t:Turn) "
            "RETURN count(t) AS total",
            {"id": session_id},
        )
        dropped = int(records[0]["total"]) if records else 0
        await self._run(
            "MATCH (s:Session {id: $id}) "
            "OPTIONAL MATCH (s)-[:HAS_TURN]->(t:Turn) "
            "DETACH DELETE t, s",
            {"id": session_id},
        )
        self._seq_cache.pop(session_id, None)
        return dropped

    async def count_sessions(self) -> int:
        records = await self._run("MATCH (s:Session) RETURN count(s) AS total", {})
        return int(records[0]["total"]) if records else 0

    async def count_turns(self) -> int:
        records = await self._run("MATCH (t:Turn) RETURN count(t) AS total", {})
        return int(records[0]["total"]) if records else 0

    @staticmethod
    def _record_to_turn(row: dict[str, Any]) -> Turn:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return Turn(
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            id=row["turn_id"],
            created_at=datetime.fromisoformat(row["created_at"])
            if row.get("created_at")
            else datetime.now(UTC),
            seq=int(row["seq"]),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    # -- GraphStore contract (lane projections) -------------------------------

    async def merge_node(
        self, label: str, key_prop: str, props: dict[str, Any]
    ) -> None:
        """Idempotently merge one labeled node keyed by ``key_prop``."""
        safe_label = label.replace("`", "")
        assignments = ", ".join(f"n.{key} = ${key}" for key in props)
        await self._run(
            f"MERGE (n:`{safe_label}` {{{key_prop}: ${key_prop}}}) SET {assignments}",
            props,
        )

    async def merge_relation(
        self,
        src_label: str,
        src_key: str,
        rel: str,
        dst_label: str,
        dst_key: str,
        *,
        src_prop: str = "id",
        dst_prop: str = "id",
        props: Mapping[str, Any] | None = None,
    ) -> None:
        """Idempotently merge one relation between two existing nodes."""
        safe_src = src_label.replace("`", "")
        safe_dst = dst_label.replace("`", "")
        safe_rel = rel.replace("`", "")
        edge_id = (props or {}).get("edge_id")
        if edge_id:
            await self._run(
                f"MATCH (a:`{safe_src}`) WHERE a.{src_prop} = $src_key "
                f"MATCH (b:`{safe_dst}`) WHERE b.{dst_prop} = $dst_key "
                f"MERGE (a)-[r:`{safe_rel}` {{edge_id: $edge_id}}]->(b) "
                f"SET r.edge_id = $edge_id",
                {
                    "src_key": src_key,
                    "dst_key": dst_key,
                    "edge_id": str(edge_id),
                },
            )
            return
        await self._run(
            f"MATCH (a:`{safe_src}`) WHERE a.{src_prop} = $src_key "
            f"MATCH (b:`{safe_dst}`) WHERE b.{dst_prop} = $dst_key "
            f"MERGE (a)-[r:`{safe_rel}`]->(b)",
            {"src_key": src_key, "dst_key": dst_key},
        )

    async def drop_node(self, label: str, key_prop: str, key_value: str) -> int:
        """Detach-delete every node of ``label`` matching the key; returns count."""
        safe_label = label.replace("`", "")
        records = await self._run(
            f"MATCH (n:`{safe_label}` {{{key_prop}: ${key_prop}}}) "
            "DETACH DELETE n RETURN count(n) AS total",
            {key_prop: key_value},
        )
        return int(records[0]["total"]) if records else 0


__all__ = [
    "CONSTRAINTS",
    "CONTENT_PREVIEW_CHARS",
    "MERGE_TURN",
    "Neo4jSessionStore",
]

"""SQLite SessionSearch: FTS5 over ``turns`` that lives in the same ``sprout_conversation.db``.

The FTS5 table is contentless (``body`` is the only indexed column) so it
does not duplicate the turn rows — search results reference back to the
authoritative ``turns`` table by ``turn_id`` when the snippet needs more
than what the index has.
"""

from __future__ import annotations

from datetime import datetime as _dt
from typing import Any

from Sprout.memory.contract import SessionSearch
from Sprout.memory.models import SearchHit
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.fts_migrate import (
    migrate_fts_tokenizer,
    table_tokenizer,
)

#: Kept under its old name because the session store imports it as the schema
#: it guarantees; the tokenizer is the only thing that changed.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED, turn_id UNINDEXED, role UNINDEXED,
    seq UNINDEXED, body, tokenize='trigram'
);
"""

#: The pre-migration definition. Still needed as a fallback for SQLite builds
#: without trigram support: a working unicode61 index beats no index at all.
FTS_SCHEMA_TRIGRAM = FTS_SCHEMA
FTS_SCHEMA_UNICODE61 = """
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED, turn_id UNINDEXED, role UNINDEXED,
    seq UNINDEXED, body, tokenize='unicode61'
);
"""

_TURN_COLUMNS = ("session_id", "turn_id", "role", "seq", "body")


class SqliteSessionSearch(SessionSearch):
    """Cross-session full-text search over the session layer."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        self.tokenizer = self._open_fts()

    def _open_fts(self) -> str:
        """Return the FTS5 table's real tokenizer, creating or upgrading it.

        The table is usually created earlier by ``SqliteSessionStore``, and
        ``CREATE VIRTUAL TABLE IF NOT EXISTS`` against an existing table is a
        silent no-op — so "the statement did not raise" is not evidence the
        tokenizer is what we asked for. Read ``sqlite_master`` and report what
        is actually there.

        A database that predates the trigram switch is rebuilt once
        (``migrate_fts_tokenizer``); only if that fails do we stay on whatever
        tokenizer it already has, because an existing index is better than
        none. Dropping ``turns_fts`` on a transient error once discarded
        searchable history and must not happen again.
        """
        try:
            self._db.executescript(FTS_SCHEMA)
        except Exception:  # noqa: BLE001 - no tokenizer is preferable to a crash
            self._db.executescript(FTS_SCHEMA_UNICODE61)
            return table_tokenizer(self._db, "turns_fts") or "unicode61"

        migrate_fts_tokenizer(self._db, "turns_fts", FTS_SCHEMA, _TURN_COLUMNS)
        return table_tokenizer(self._db, "turns_fts") or "unicode61"

    async def index_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_seq: int,
        role: str,
        body: str,
    ) -> None:
        # Idempotent by ``turn_id``: the fan-out mirror indexes a turn as it
        # is appended and the outbox worker may deliver the same turn again,
        # so replace any prior row rather than accumulating duplicates.
        await self._db.execute(
            "DELETE FROM turns_fts WHERE turn_id = ?", (turn_id,)
        )
        await self._db.execute(
            "INSERT INTO turns_fts(session_id, turn_id, role, seq, body) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, turn_id, turn_seq, role, body),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        try:
            if session_id is None:
                rows = await self._db.fetchall(
                    "SELECT session_id, turn_id, seq, "
                    "snippet(turns_fts, 4, '|', '|', '…', 12) AS snip "
                    "FROM turns_fts WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                    (query, limit),
                )
            else:
                rows = await self._db.fetchall(
                    "SELECT session_id, turn_id, seq, "
                    "snippet(turns_fts, 4, '|', '|', '…', 12) AS snip "
                    "FROM turns_fts WHERE turns_fts MATCH ? AND session_id = ? "
                    "ORDER BY rank LIMIT ?",
                    (query, session_id, limit),
                )
        except Exception:  # noqa: BLE001 - parser fallback
            return await self._like(query, limit=limit, session_id=session_id)
        return [
            SearchHit(
                session_id=r["session_id"],
                turn_seq=r["seq"],
                turn_id=r["turn_id"],
                snippet=r["snip"],
            )
            for r in rows
        ]

    async def _like(
        self, query: str, *, limit: int, session_id: str | None
    ) -> list[SearchHit]:
        like = f"%{query}%"
        if session_id is None:
            rows = await self._db.fetchall(
                "SELECT session_id, turn_id, seq, body FROM turns_fts "
                "WHERE body LIKE ? ORDER BY seq DESC LIMIT ?",
                (like, limit),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT session_id, turn_id, seq, body FROM turns_fts "
                "WHERE body LIKE ? AND session_id = ? ORDER BY seq DESC LIMIT ?",
                (like, session_id, limit),
            )
        return [
            SearchHit(
                session_id=r["session_id"],
                turn_seq=r["seq"],
                turn_id=r["turn_id"],
                snippet=r["body"][:160],
            )
            for r in rows
        ]

    async def unindex_session(self, session_id: str) -> int:
        await self._db.execute(
            "DELETE FROM turns_fts WHERE session_id = ?", (session_id,)
        )
        return 1


class MemorySessionSearch(SessionSearch):
    """In-memory SessionSearch used by tests and the in-memory bundle."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], tuple[int, str, str]] = {}

    async def index_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_seq: int,
        role: str,
        body: str,
    ) -> None:
        self._rows[(session_id, turn_id)] = (turn_seq, role, body)

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[SearchHit]:
        tokens = [t for t in query.split() if t]
        hits: list[SearchHit] = []
        for (sid, tid), (seq, _role, body) in self._rows.items():
            if session_id is not None and sid != session_id:
                continue
            if not tokens or all(t.lower() in body.lower() for t in tokens):
                hits.append(
                    SearchHit(
                        session_id=sid,
                        turn_seq=seq,
                        turn_id=tid,
                        snippet=body[:160],
                    )
                )
        hits.sort(key=lambda h: h.turn_seq, reverse=True)
        return hits[:limit]

    async def unindex_session(self, session_id: str) -> int:
        keys = [k for k in self._rows if k[0] == session_id]
        for k in keys:
            self._rows.pop(k, None)
        return len(keys)


__all__ = [
    "SqliteSessionSearch",
    "MemorySessionSearch",
    "FTS_SCHEMA",
    "FTS_SCHEMA_TRIGRAM",
    "FTS_SCHEMA_UNICODE61",
]


_ = _dt  # noqa: F841
_ = Any  # noqa: F841

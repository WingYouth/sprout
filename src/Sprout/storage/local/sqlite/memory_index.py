"""SQLite memory-fact index: FTS5 over the curated memory layer.

The authority for memory facts stays with the memory layer (markdown files
under the memory home, Hermes-style). This index is the *derived* SQLite
lane: every fact gets a searchable row so ``sprout memory search`` works
without reading and parsing the whole file, and the six-lane fan-out keeps
it in sync on every add/replace/remove.
"""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.fts_migrate import migrate_fts_tokenizer

#: ``trigram`` rather than ``unicode61``: unicode61 treats a whole CJK sentence
#: as one token, so a Chinese sub-phrase (``存储层`` inside ``存储层设计``) never
#: matched. Databases created before this keep unicode61 through
#: ``IF NOT EXISTS``, so they are rebuilt once by :func:`migrate_fts_tokenizer`.
SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    scope UNINDEXED, owner UNINDEXED, fact_key UNINDEXED, body,
    tokenize='trigram'
);
"""

_MEMORY_COLUMNS = ("scope", "owner", "fact_key", "body")


@dataclass(frozen=True, slots=True)
class MemoryFactHit:
    """One full-text match over the memory layer."""

    scope: str  # "session" | "user"
    owner: str  # session_id or user_id
    fact_key: str
    snippet: str


class SqliteMemoryIndex:
    """Derived FTS index over session and user facts (SQLite lane)."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)
        migrate_fts_tokenizer(db, "memory_fts", SCHEMA, _MEMORY_COLUMNS)

    async def index_fact(
        self, scope: str, owner: str, fact_key: str, body: str
    ) -> None:
        await self._db.execute_batch(
            [
                (
                    "DELETE FROM memory_fts WHERE scope = ? AND owner = ? "
                    "AND fact_key = ?",
                    (scope, owner, fact_key),
                ),
                (
                    "INSERT INTO memory_fts (scope, owner, fact_key, body) "
                    "VALUES (?, ?, ?, ?)",
                    (scope, owner, fact_key, body),
                ),
            ]
        )

    async def search(self, query: str, *, limit: int = 10) -> list[MemoryFactHit]:
        rows = await self._db.fetchall(
            "SELECT scope, owner, fact_key, snippet(memory_fts, 3, '[', ']', '…', 12) "
            "AS snippet FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?",
            (query, limit),
        )
        return [
            MemoryFactHit(
                scope=row["scope"],
                owner=row["owner"],
                fact_key=row["fact_key"],
                snippet=row["snippet"],
            )
            for row in rows
        ]

    async def drop_owner(self, scope: str, owner: str) -> int:
        before = int(
            await self._db.scalar(
                "SELECT COUNT(*) FROM memory_fts WHERE scope = ? AND owner = ?",
                (scope, owner),
            )
            or 0
        )
        await self._db.execute(
            "DELETE FROM memory_fts WHERE scope = ? AND owner = ?", (scope, owner)
        )
        return before

    async def count(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM memory_fts") or 0)


__all__ = ["MemoryFactHit", "SCHEMA", "SqliteMemoryIndex"]

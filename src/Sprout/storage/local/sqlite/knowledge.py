"""SQLite knowledge store (sprout_knowledge.db)."""

from __future__ import annotations

import json
from datetime import datetime

from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas

# Base tables live separately from the FTS shadow so column migrations can run
# between the two executescript passes (see SqliteKnowledgeStore.__init__).
_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    kind TEXT NOT NULL DEFAULT 'knowledge',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    content_blob_uri TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind, status);
CREATE TABLE IF NOT EXISTS memory_fact (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    owner_id TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_json TEXT NOT NULL DEFAULT '{}',
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_fact_owner ON memory_fact(scope, owner_id);
CREATE TABLE IF NOT EXISTS capability_note (
    id TEXT PRIMARY KEY,
    capability_name TEXT NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'low',
    usage_pattern TEXT NOT NULL DEFAULT '',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    examples_blob_uri TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_evidence (
    knowledge_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    quote_blob_uri TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (knowledge_id, source_type, source_id)
);
CREATE TABLE IF NOT EXISTS knowledge_link (
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, target_type, target_id, relation)
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title,
    content,
    kind,
    scope,
    content='knowledge',
    content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, kind, scope)
    VALUES (new.rowid, new.title, new.content, new.kind, new.scope);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, kind, scope)
    VALUES ('delete', old.rowid, old.title, old.content, old.kind, old.scope);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, kind, scope)
    VALUES ('delete', old.rowid, old.title, old.content, old.kind, old.scope);
    INSERT INTO knowledge_fts(rowid, title, content, kind, scope)
    VALUES (new.rowid, new.title, new.content, new.kind, new.scope);
END;
"""

# Index that depends on Guidance §19.2 columns, so it runs after the ALTER pass.
_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge(scope, status);
"""

# Combined schema, kept for callers/tests that import ``SCHEMA`` directly.
SCHEMA = _TABLE_SCHEMA + _INDEX_SCHEMA + _FTS_SCHEMA

# Columns added by Guidance §19.2 that older knowledge tables may be missing.
_KNOWLEDGE_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("scope", "TEXT NOT NULL DEFAULT 'global'"),
    ("title", "TEXT NOT NULL DEFAULT ''"),
    ("content_blob_uri", "TEXT"),
    ("confidence", "REAL NOT NULL DEFAULT 1.0"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
)
_KNOWLEDGE_FTS_COLUMNS = ("title", "content", "kind", "scope")

_SEARCH_SCAN_LIMIT = 500


def _migrate_knowledge_columns(db: SqliteDatabase) -> None:
    """Add Guidance §19.2 columns missing from a pre-existing knowledge table."""
    existing = {row["name"] for row in db.fetchall_sync("PRAGMA table_info(knowledge)")}
    for name, decl in _KNOWLEDGE_COLUMN_MIGRATIONS:
        if name not in existing:
            db.execute_sync(f"ALTER TABLE knowledge ADD COLUMN {name} {decl}")


def _migrate_knowledge_fts(db: SqliteDatabase) -> None:
    """Drop a legacy FTS shadow so ``_FTS_SCHEMA`` can rebuild it with new columns."""
    columns = tuple(row["name"] for row in db.fetchall_sync("PRAGMA table_info(knowledge_fts)"))
    if not columns or columns == _KNOWLEDGE_FTS_COLUMNS:
        return
    db.executescript(
        """
        DROP TRIGGER IF EXISTS knowledge_fts_insert;
        DROP TRIGGER IF EXISTS knowledge_fts_delete;
        DROP TRIGGER IF EXISTS knowledge_fts_update;
        DROP TABLE IF EXISTS knowledge_fts;
        """
    )


class SqliteKnowledgeStore:
    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(_TABLE_SCHEMA)
        _migrate_knowledge_columns(db)
        db.executescript(_INDEX_SCHEMA)
        _migrate_knowledge_fts(db)
        db.executescript(_FTS_SCHEMA)
        self._backfill_fts()

    def _backfill_fts(self) -> None:
        """Populate FTS from any pre-existing rows that predate the index."""
        # ``INSERT INTO ... SELECT`` is a no-op when FTS already holds the rows
        # because FTS5 deduplicates by rowid on conflict via this trigger path;
        # a fresh table starts empty so the select covers the full authority set.
        self._db.executescript(
            """
            INSERT INTO knowledge_fts(rowid, title, content, kind, scope)
            SELECT rowid, title, content, kind, scope FROM knowledge
            WHERE rowid NOT IN (SELECT rowid FROM knowledge_fts);
            """
        )

    def close(self) -> None:
        self._db.close()

    async def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Ranked full-text search over active items, falling back to keywords."""
        query = query.strip()
        if not query:
            return []

        # FTS5 tokenises with its own grammar; a raw user phrase still works as
        # an AND query via the implicit query builder.
        try:
            fts_rows = await self._db.fetchall(
                """
                SELECT k.id, k.scope, k.kind, k.title, k.content, k.content_blob_uri,
                       k.evidence_json, k.status, k.version, k.confidence,
                       k.created_at, k.updated_at, bm25(knowledge_fts) AS rank
                FROM knowledge_fts
                JOIN knowledge k ON k.rowid = knowledge_fts.rowid
                WHERE knowledge_fts MATCH ?
                  AND k.status = 'active'
                ORDER BY rank
                LIMIT ?
                """,
                (query, max(1, limit)),
            )
        except Exception:  # noqa: BLE001 - malformed FTS query; keyword fallback below
            fts_rows = []
        if fts_rows:
            return [self._row_to_item(row) for row in fts_rows]

        words = {word.casefold() for word in query.split() if word.strip()}
        rows = await self._db.fetchall(
            "SELECT * FROM knowledge WHERE status = 'active' LIMIT ?",
            (_SEARCH_SCAN_LIMIT,),
        )
        items = [self._row_to_item(row) for row in rows]
        ranked = sorted(
            items,
            key=lambda item: len(words.intersection(item.content.casefold().split())),
            reverse=True,
        )
        return [item for item in ranked if any(w in item.content.casefold() for w in words)][
            :limit
        ]

    async def put(self, item: KnowledgeItem) -> None:
        await self._db.execute(
            "INSERT INTO knowledge (id, scope, kind, title, content, content_blob_uri, "
            "evidence_json, status, version, confidence, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET scope = excluded.scope, "
            "kind = excluded.kind, title = excluded.title, content = excluded.content, "
            "content_blob_uri = excluded.content_blob_uri, "
            "evidence_json = excluded.evidence_json, status = excluded.status, "
            "version = excluded.version, confidence = excluded.confidence, "
            "updated_at = excluded.updated_at",
            (
                item.id,
                item.scope,
                item.kind,
                item.title,
                item.content,
                item.content_blob_uri,
                json.dumps(list(item.evidence_ids)),
                item.status,
                item.version,
                item.confidence,
                item.created_at.isoformat(),
                (item.updated_at or item.created_at).isoformat(),
            ),
        )

    async def get(self, item_id: str) -> KnowledgeItem | None:
        row = await self._db.fetchone("SELECT * FROM knowledge WHERE id = ?", (item_id,))
        return self._row_to_item(row) if row else None

    async def list_items(
        self, kind: str | None = None, limit: int = 100
    ) -> list[KnowledgeItem]:
        if kind is None:
            rows = await self._db.fetchall(
                "SELECT * FROM knowledge WHERE status = 'active' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM knowledge WHERE status = 'active' AND kind = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            )
        return [self._row_to_item(row) for row in rows]

    async def count(self) -> int:
        return int(await self._db.scalar("SELECT COUNT(*) FROM knowledge") or 0)

    @staticmethod
    def _row_to_item(row: object) -> KnowledgeItem:
        return KnowledgeItem(
            id=row["id"],  # type: ignore[index]
            content=row["content"],  # type: ignore[index]
            kind=row["kind"],  # type: ignore[index]
            evidence_ids=tuple(json.loads(row["evidence_json"])),  # type: ignore[index]
            version=int(row["version"]),  # type: ignore[index]
            status=row["status"],  # type: ignore[index]
            created_at=datetime.fromisoformat(row["created_at"]),  # type: ignore[index]
            scope=row["scope"],  # type: ignore[index]
            title=row["title"],  # type: ignore[index]
            content_blob_uri=row["content_blob_uri"],  # type: ignore[index]
            confidence=float(row["confidence"]),  # type: ignore[index]
            updated_at=datetime.fromisoformat(  # type: ignore[index]
                row["updated_at"] or row["created_at"]
            ),
        )


def open_knowledge_store(
    path: str, pragmas: SqlitePragmas | None = None
) -> SqliteKnowledgeStore:
    """Open (and reserve) a sprout_knowledge.db at ``path``, creating the schema if needed."""
    return SqliteKnowledgeStore(SqliteDatabase.open(path, pragmas))

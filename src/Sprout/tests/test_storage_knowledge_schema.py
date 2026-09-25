"""Regression tests for Guidance §19.2 knowledge/memory schema coverage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.knowledge import SqliteKnowledgeStore, open_knowledge_store

_GUIDANCE_KNOWLEDGE_COLUMNS = [
    "id",
    "scope",
    "kind",
    "title",
    "content",
    "content_blob_uri",
    "evidence_json",
    "status",
    "version",
    "confidence",
    "created_at",
    "updated_at",
]
_GUIDANCE_MEMORY_FACT_COLUMNS = [
    "id",
    "scope",
    "owner_id",
    "key",
    "value",
    "confidence",
    "source_json",
    "expires_at",
    "created_at",
    "updated_at",
]


def _columns(db: SqliteDatabase, table: str) -> list[str]:
    return [row["name"] for row in db.fetchall_sync(f"PRAGMA table_info({table})")]


def test_fresh_schema_declares_guidance_tables(tmp_path) -> None:
    db = SqliteDatabase.open(str(tmp_path / "sprout_knowledge.db"))
    SqliteKnowledgeStore(db)
    tables = {
        row["name"] for row in db.fetchall_sync("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in (
        "knowledge",
        "memory_fact",
        "capability_note",
        "knowledge_evidence",
        "knowledge_link",
    ):
        assert expected in tables, expected
    assert _columns(db, "knowledge") == _GUIDANCE_KNOWLEDGE_COLUMNS
    assert _columns(db, "memory_fact") == _GUIDANCE_MEMORY_FACT_COLUMNS
    assert _columns(db, "capability_note") == [
        "id",
        "capability_name",
        "tool_name",
        "risk_level",
        "usage_pattern",
        "constraints_json",
        "examples_blob_uri",
        "updated_at",
    ]
    assert _columns(db, "knowledge_evidence") == [
        "knowledge_id",
        "source_type",
        "source_id",
        "weight",
        "quote_blob_uri",
        "created_at",
    ]
    assert _columns(db, "knowledge_link") == [
        "source_id",
        "target_type",
        "target_id",
        "relation",
        "weight",
        "created_at",
    ]
    assert _columns(db, "knowledge_fts") == ["title", "content", "kind", "scope"]
    db.close()


async def test_put_get_round_trips_guidance_columns(tmp_path) -> None:
    store = open_knowledge_store(str(tmp_path / "sprout_knowledge.db"))
    created = datetime(2026, 9, 22, tzinfo=UTC)
    await store.put(
        KnowledgeItem(
            id="k-1",
            content="sqlite keeps data local",
            kind="knowledge",
            scope="project",
            title="Local storage",
            content_blob_uri="blob://k-1",
            confidence=0.75,
            created_at=created,
        )
    )
    got = await store.get("k-1")
    assert got is not None
    assert got.scope == "project"
    assert got.title == "Local storage"
    assert got.content_blob_uri == "blob://k-1"
    assert got.confidence == 0.75
    # updated_at is absent on the contract, so it falls back to created_at.
    assert got.updated_at == created
    store.close()


async def test_search_matches_indexed_title(tmp_path) -> None:
    store = open_knowledge_store(str(tmp_path / "sprout_knowledge.db"))
    await store.put(KnowledgeItem(id="k-1", content="body text", title="Orchard harvest"))
    hits = await store.search("Orchard")
    assert [hit.id for hit in hits] == ["k-1"]
    store.close()


async def test_legacy_knowledge_table_is_migrated(tmp_path) -> None:
    path = tmp_path / "sprout_knowledge.db"
    legacy = sqlite3.connect(str(path))
    legacy.executescript(
        """
        CREATE TABLE knowledge (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'knowledge',
            content TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE knowledge_fts USING fts5(
            content, kind, content='knowledge', content_rowid='rowid'
        );
        INSERT INTO knowledge (id, kind, content, created_at)
        VALUES ('legacy-1', 'knowledge', 'old row', '2026-09-01T00:00:00+00:00');
        """
    )
    legacy.commit()
    legacy.close()

    store = open_knowledge_store(str(path))
    # ALTER TABLE can only append columns, so compare as sets for the legacy path.
    assert sorted(_columns(store._db, "knowledge")) == sorted(_GUIDANCE_KNOWLEDGE_COLUMNS)
    assert _columns(store._db, "knowledge_fts") == ["title", "content", "kind", "scope"]
    item = await store.get("legacy-1")
    assert item is not None
    assert item.scope == "global"
    assert item.content == "old row"
    hits = await store.search("old")
    assert [hit.id for hit in hits] == ["legacy-1"]
    store.close()

"""Existing ``unicode61`` FTS tables must be migrated to ``trigram``.

``CREATE VIRTUAL TABLE IF NOT EXISTS`` is a silent no-op against an existing
table, so a database created before the tokenizer change keeps unicode61
forever and CJK sub-phrase search keeps returning nothing. Making new
databases trigram is not enough — the index has to be rebuilt once, without
losing the rows already indexed.
"""

from __future__ import annotations

import pytest

from Sprout.memory.backends.session_search import SqliteSessionSearch
from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.storage.local.sqlite.driver import SqliteDatabase

#: The schema these tables had before the switch.
LEGACY_TURNS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED, turn_id UNINDEXED, role UNINDEXED,
    seq UNINDEXED, body, tokenize='unicode61'
);
"""

LEGACY_MEMORY_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    scope UNINDEXED, owner UNINDEXED, fact_key UNINDEXED, body,
    tokenize='unicode61'
);
"""


def _tokenizer(db: SqliteDatabase, table: str) -> str | None:
    rows = db.fetchall_sync("SELECT sql FROM sqlite_master WHERE name = ?", (table,))
    if not rows:
        return None
    definition = str(rows[0]["sql"] or "")
    for candidate in ("trigram", "unicode61"):
        if candidate in definition:
            return candidate
    return None


def _legacy_db(tmp_path, name: str = "conv.db") -> SqliteDatabase:
    """A database as it existed before the tokenizer change, with content."""
    db = SqliteDatabase(str(tmp_path / name))
    db.executescript(LEGACY_TURNS_FTS)
    db.executescript(LEGACY_MEMORY_FTS)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS turns ("
        "id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT);"
    )
    db.execute_sync(
        "INSERT INTO turns_fts(session_id, turn_id, role, seq, body) VALUES (?,?,?,?,?)",
        ("s1", "t1", "user", 1, "项目分析与存储层设计"),
    )
    db.execute_sync(
        "INSERT INTO memory_fts(scope, owner, fact_key, body) VALUES (?,?,?,?)",
        ("user", "u1", "prefs", "偏好使用中文注释"),
    )
    assert _tokenizer(db, "turns_fts") == "unicode61"
    return db


def test_legacy_unicode61_turns_table_is_migrated_to_trigram(tmp_path) -> None:
    db = _legacy_db(tmp_path)
    SqliteSessionSearch(db)

    assert _tokenizer(db, "turns_fts") == "trigram"


def test_migration_preserves_indexed_turns(tmp_path) -> None:
    """Rebuilding must not silently discard searchable history."""
    db = _legacy_db(tmp_path)
    SqliteSessionSearch(db)

    rows = db.fetchall_sync("SELECT turn_id, body FROM turns_fts")
    assert [r["turn_id"] for r in rows] == ["t1"]
    assert rows[0]["body"] == "项目分析与存储层设计"


def test_migrated_index_answers_cjk_sub_phrase_queries(tmp_path) -> None:
    db = _legacy_db(tmp_path)
    SqliteSessionSearch(db)

    rows = db.fetchall_sync(
        "SELECT turn_id FROM turns_fts WHERE turns_fts MATCH ?", ("存储层",)
    )
    assert rows, "the migrated index still cannot match a CJK sub-phrase"


def test_migration_is_idempotent(tmp_path) -> None:
    db = _legacy_db(tmp_path)
    SqliteSessionSearch(db)
    SqliteSessionSearch(db)  # second open must not rebuild or lose rows

    assert _tokenizer(db, "turns_fts") == "trigram"
    assert len(db.fetchall_sync("SELECT turn_id FROM turns_fts")) == 1


def test_already_trigram_table_is_left_alone(tmp_path) -> None:
    db = SqliteDatabase(str(tmp_path / "conv.db"))
    SqliteSessionStore(db)
    assert _tokenizer(db, "turns_fts") == "trigram"

    db.execute_sync(
        "INSERT INTO turns_fts(session_id, turn_id, role, seq, body) VALUES (?,?,?,?,?)",
        ("s1", "t1", "user", 1, "存储层"),
    )
    SqliteSessionSearch(db)

    assert _tokenizer(db, "turns_fts") == "trigram"
    assert len(db.fetchall_sync("SELECT turn_id FROM turns_fts")) == 1


def test_an_interrupted_migration_does_not_duplicate_rows(tmp_path) -> None:
    """Crash between the copy and the swap, then retry: rows must not double.

    The staging table is created with ``IF NOT EXISTS``, so a run killed after
    ``INSERT ... SELECT`` but before the swap leaves ``turns_fts_migrating``
    half-filled on disk. The next open retries the migration — and if the
    leftover is reused, its rows are appended a second time and every indexed
    turn is duplicated in search results. ``_discard_leftovers`` only ran on the
    success path, so nothing cleaned up before the copy.
    """
    db = _legacy_db(tmp_path)
    # A second turn, so a duplication is unmistakable rather than a coincidence.
    db.execute_sync(
        "INSERT INTO turns_fts(session_id, turn_id, role, seq, body) VALUES (?,?,?,?,?)",
        ("s1", "t2", "assistant", 2, "存储层设计说明"),
    )
    before = len(db.fetchall_sync("SELECT turn_id FROM turns_fts"))
    assert before == 2

    # The interrupted run: staging table built and populated, swap never reached.
    # Rebuild it exactly the way ``migrate_fts_tokenizer`` would, i.e. from the
    # *target* schema — the staging table is a trigram twin of ``turns_fts``.
    from Sprout.memory.backends.session_search import FTS_SCHEMA

    db.executescript(FTS_SCHEMA.replace(" turns_fts ", " turns_fts_migrating ", 1))
    db.execute_sync(
        "INSERT INTO turns_fts_migrating (session_id, turn_id, role, seq, body) "
        "SELECT session_id, turn_id, role, seq, body FROM turns_fts"
    )

    SqliteSessionSearch(db)  # the retry

    assert _tokenizer(db, "turns_fts") == "trigram"
    assert len(db.fetchall_sync("SELECT turn_id FROM turns_fts")) == before, (
        "the retry appended the row set a second time"
    )


def test_legacy_memory_fts_is_migrated_too(tmp_path) -> None:
    """The memory index had the same unicode61 flaw (second call site)."""
    from Sprout.storage.local.sqlite.memory_index import SqliteMemoryIndex

    db = _legacy_db(tmp_path, "mem.db")
    index = SqliteMemoryIndex(db)

    assert _tokenizer(db, "memory_fts") == "trigram"

    @pytest.mark.asyncio
    async def _check() -> None:
        hits = await index.search("中文注释", limit=5)
        assert hits, "memory search still cannot match a CJK sub-phrase"
        assert hits[0].fact_key == "prefs"

    import asyncio

    asyncio.run(_check())

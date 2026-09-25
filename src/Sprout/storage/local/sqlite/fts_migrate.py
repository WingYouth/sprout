"""One-time rebuild of FTS5 tables that predate the ``trigram`` tokenizer.

Two indexes were created with ``tokenize='unicode61'``: ``turns_fts`` in
``sprout_conversation.db`` and ``memory_fts``. unicode61 treats a whole CJK
sentence as a single token, so a Chinese sub-phrase query (``存储层`` inside
``项目分析与存储层设计``) matched nothing.

Switching the ``CREATE VIRTUAL TABLE`` statement only helps databases created
afterwards: ``IF NOT EXISTS`` is a silent no-op against an existing table, so
every database already on disk kept the old tokenizer with no way to change it.
This module rebuilds the table once, copying the rows across.

Ordering is deliberate. The new table is built and populated *beside* the old
one, and the old one is only dropped after the copy succeeds. A failure part
way through leaves the original index intact and the migration simply retries
on the next open.
"""

from __future__ import annotations

import logging

from Sprout.storage.local.sqlite.driver import SqliteDatabase

logger = logging.getLogger("sprout.storage.fts")

#: Tokenizer every FTS table should be on.
TARGET_TOKENIZER = "trigram"


def table_tokenizer(db: SqliteDatabase, table: str) -> str | None:
    """The tokenizer named in a live FTS table's definition, or None if absent."""
    rows = db.fetchall_sync("SELECT sql FROM sqlite_master WHERE name = ?", (table,))
    if not rows:
        return None
    definition = str(rows[0]["sql"] or "")
    for candidate in (TARGET_TOKENIZER, "unicode61"):
        if candidate in definition:
            return candidate
    return None


def migrate_fts_tokenizer(
    db: SqliteDatabase,
    table: str,
    create_sql: str,
    columns: tuple[str, ...],
) -> bool:
    """Rebuild ``table`` on the trigram tokenizer if it is not already there.

    ``create_sql`` must be the statement that creates the table under its final
    name; the temp name is substituted so the definition stays single-sourced
    with the schema modules. Returns True when a rebuild happened.
    """
    current = table_tokenizer(db, table)
    if current is None:
        return False
    if current == TARGET_TOKENIZER:
        # Recover a half-finished run from a previous process death: the swap
        # below renames the old table aside before the new one takes its name.
        _discard_leftovers(db, table)
        return False

    temporary = f"{table}_migrating"
    column_list = ", ".join(columns)
    try:
        # Clear any staging table a previous run left behind *before* creating
        # one. The CREATE below is ``IF NOT EXISTS`` (it is substituted into the
        # schema module's own statement), so without this the copy would append
        # a second time to a half-filled leftover and every row would be
        # duplicated — the exact loss this migration exists to prevent. The
        # leftover holds nothing not already in ``table``, so dropping it is
        # safe; ``table`` itself is untouched until the swap below.
        db.executescript(f"DROP TABLE IF EXISTS {temporary};")
        # The temp name is substituted into the caller's own CREATE statement so
        # the column list and options stay single-sourced with the schema module.
        db.executescript(create_sql.replace(f" {table} ", f" {temporary} ", 1))
        db.execute_sync(
            f"INSERT INTO {temporary} ({column_list}) SELECT {column_list} FROM {table}"
        )
        # The copy succeeded; swap the tables. The original is only dropped once
        # its replacement is in place, so an interrupted run never loses rows.
        db.executescript(f"DROP TABLE {table};")
        db.executescript(f"ALTER TABLE {temporary} RENAME TO {table};")
    except Exception:  # noqa: BLE001 - keep the old index rather than crash
        logger.warning("FTS migration of %s failed; keeping the existing index", table)
        try:
            db.executescript(f"DROP TABLE IF EXISTS {temporary};")
        except Exception:  # noqa: BLE001
            pass
        return False

    _discard_leftovers(db, table)
    logger.info("Migrated %s to the %s tokenizer", table, TARGET_TOKENIZER)
    return True


def _discard_leftovers(db: SqliteDatabase, table: str) -> None:
    """Drop any staging table left behind by an interrupted migration."""
    for leftover in (f"{table}_old", f"{table}_migrating"):
        try:
            db.executescript(f"DROP TABLE IF EXISTS {leftover};")
        except Exception:  # noqa: BLE001
            logger.debug("Could not drop leftover table %s", leftover)


__all__ = ["TARGET_TOKENIZER", "migrate_fts_tokenizer", "table_tokenizer"]

"""Tests for ``sprout storage migrate`` (the topology disposition executor)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from Sprout.storage.migrate import _target_from_action, run_migration

_SESSION_DDL = (
    "CREATE TABLE sessions ("
    "id TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, metadata_json TEXT)"
)


def _make_db(path: Path, ddl: str, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute(ddl)
    if rows:
        placeholders = ",".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO sessions VALUES ({placeholders})", rows)
    con.commit()
    con.close()


def _row_ids(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT id FROM sessions ORDER BY id")]
    finally:
        con.close()


def test_target_from_action_parses_only_sqlite_files() -> None:
    assert _target_from_action("migrate-to sprout_audit.db") == "sprout_audit.db"
    assert _target_from_action("merge-into sprout_conversation.db FTS") == (
        "sprout_conversation.db"
    )
    # A non-file authority must not be mistaken for a target database.
    assert _target_from_action("migrate-to derived context index") is None
    assert _target_from_action("delete") is None


def test_dry_run_reports_without_touching_disk(tmp_path: Path) -> None:
    _make_db(tmp_path / "session.db", _SESSION_DDL, [("s1", "u", "t1", "{}")])
    _make_db(tmp_path / "sprout_conversation.db", _SESSION_DDL, [("s0", "u", "t0", "{}")])

    report = run_migration(apply=False, data_root=tmp_path)

    assert report["applied"] is False
    assert report["backup"] is None
    entry = next(e for e in report["entries"] if e["source"] == "session.db")
    assert entry["status"] == "would-migrate"
    assert entry["target"] == "sprout_conversation.db"
    # Nothing moved.
    assert (tmp_path / "session.db").exists()
    assert _row_ids(tmp_path / "sprout_conversation.db") == ["s0"]


def test_apply_moves_rows_and_archives_source(tmp_path: Path) -> None:
    _make_db(
        tmp_path / "session.db",
        _SESSION_DDL,
        [("s1", "u", "t1", "{}"), ("s2", "u", "t2", "{}")],
    )
    _make_db(tmp_path / "sprout_conversation.db", _SESSION_DDL, [("s0", "u", "t0", "{}")])

    report = run_migration(apply=True, data_root=tmp_path)

    assert report["applied"] is True
    entry = next(e for e in report["entries"] if e["source"] == "session.db")
    assert entry["status"] == "migrated"
    # Rows landed in the authority, source file drained into the archive.
    assert _row_ids(tmp_path / "sprout_conversation.db") == ["s0", "s1", "s2"]
    assert not (tmp_path / "session.db").exists()
    assert (tmp_path / "archive" / "legacy" / "session.db").exists()
    # A pre-migration backup was taken.
    assert Path(report["backup"]).is_dir()


def test_apply_is_idempotent(tmp_path: Path) -> None:
    _make_db(tmp_path / "session.db", _SESSION_DDL, [("s1", "u", "t1", "{}")])
    _make_db(tmp_path / "sprout_conversation.db", _SESSION_DDL, [("s0", "u", "t0", "{}")])

    run_migration(apply=True, data_root=tmp_path)
    second = run_migration(apply=True, data_root=tmp_path)

    # Source is gone, so the second pass has nothing to do and adds no rows.
    assert all(e["source"] != "session.db" for e in second["entries"])
    assert _row_ids(tmp_path / "sprout_conversation.db") == ["s0", "s1"]


def test_delete_disposition_archives_without_deleting(tmp_path: Path) -> None:
    _make_db(tmp_path / "herness.db", _SESSION_DDL, [("h1", "u", "t1", "{}")])

    run_migration(apply=True, data_root=tmp_path)

    # ``delete`` is honoured conservatively: archived, never destroyed.
    assert (tmp_path / "archive" / "legacy" / "herness.db").exists()


def test_non_file_target_falls_back_to_archive(tmp_path: Path) -> None:
    _make_db(tmp_path / "context.db", _SESSION_DDL, [("c1", "u", "t1", "{}")])

    report = run_migration(apply=True, data_root=tmp_path)

    entry = next(e for e in report["entries"] if e["source"] == "context.db")
    assert entry["target"] == ""
    assert entry["status"] == "archived"
    assert (tmp_path / "archive" / "legacy" / "context.db").exists()


def test_columns_absent_from_target_are_skipped(tmp_path: Path) -> None:
    # Source carries an extra column the authority does not know about.
    _make_db(
        tmp_path / "session.db",
        "CREATE TABLE sessions ("
        "id TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, metadata_json TEXT,"
        "legacy_only TEXT)",
        [("s1", "u", "t1", "{}", "junk")],
    )
    _make_db(tmp_path / "sprout_conversation.db", _SESSION_DDL, [])

    run_migration(apply=True, data_root=tmp_path)

    con = sqlite3.connect(tmp_path / "sprout_conversation.db")
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(sessions)")]
        assert "legacy_only" not in cols
        assert con.execute("SELECT id FROM sessions").fetchall() == [("s1",)]
    finally:
        con.close()

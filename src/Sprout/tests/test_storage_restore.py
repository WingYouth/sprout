"""``sprout storage restore`` must actually copy the backup it is given.

Regression: ``restore`` opened ``target_dir / file.name`` (creating an empty
database when absent), checkpointed and ``quick_check``-ed that empty file, and
reported "Restored: ...". No copy ever happened, and ``--target`` defaults to
the source directory, so the common invocation silently manufactured empty
schema files next to the backup and declared success.
"""

from __future__ import annotations

import sqlite3

import pytest


def _make_source_db(path) -> None:
    """A backup file with one table and one row, closed cleanly."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE markers (id INTEGER PRIMARY KEY, note TEXT)")
    conn.execute("INSERT INTO markers (note) VALUES ('from-the-backup')")
    conn.commit()
    conn.close()


def _row_count(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT count(*) FROM markers").fetchone()[0]
    except sqlite3.OperationalError:
        return -1  # table absent — i.e. an empty schema
    finally:
        conn.close()


def test_restore_copies_backup_into_target(tmp_path, monkeypatch) -> None:
    from Sprout.cli.commands import storage as storage_cmd

    source = tmp_path / "backup"
    source.mkdir()
    _make_source_db(source / "operational.db")

    target = tmp_path / "restored"
    storage_cmd.restore(source=str(source), target=str(target))

    restored = target / "operational.db"
    assert restored.exists(), "restore produced no file in --target"
    assert _row_count(restored) == 1, "restore created an empty database"


def test_restored_database_is_readable(tmp_path) -> None:
    """The restored copy must be a working database, not just a present file."""
    from Sprout.cli.commands import storage as storage_cmd

    source = tmp_path / "backup"
    source.mkdir()
    _make_source_db(source / "operational.db")

    target = tmp_path / "restored"
    storage_cmd.restore(source=str(source), target=str(target))

    conn = sqlite3.connect(str(target / "operational.db"))
    try:
        assert conn.execute("SELECT note FROM markers").fetchone()[0] == "from-the-backup"
    finally:
        conn.close()


def test_restore_refuses_to_overwrite_the_backup_in_place(tmp_path) -> None:
    """``--target`` defaults to the source; that must not silently self-destruct."""
    import typer

    from Sprout.cli.commands import storage as storage_cmd

    source = tmp_path / "backup"
    source.mkdir()
    db = source / "operational.db"
    _make_source_db(db)

    with pytest.raises(typer.BadParameter):
        storage_cmd.restore(source=str(source), target=None)

    assert _row_count(db) == 1, "the backup was opened in place and is no longer intact"

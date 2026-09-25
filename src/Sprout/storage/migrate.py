"""Execute the storage topology's rehome dispositions (落库-4).

``storage/topology.py`` declares what should happen to every legacy SQLite file
under ``~/.sprout/data/`` (``migrate-to X`` / ``merge-into X`` / ``delete``), but
until now nothing carried the declaration out — ``storage plan`` only displayed
it, and the ``storage`` CLI had no ``migrate`` subcommand.

This module is the executor. For each non-active disposition it copies rows into
the target authority table-by-table (column intersection, ``INSERT OR IGNORE``,
so re-running is safe), then archives the drained source file. Both source and
target are copied into a timestamped backup directory before any write happens.
Dry run by default; ``--apply`` performs the move.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from Sprout.storage.topology import STORAGE_DATABASES

_SPROUT_DATA = Path.home() / ".sprout" / "data"
_SQLITE_SUFFIXES = ("", "-wal", "-shm")
_VERBS = ("migrate-to", "merge-into")


def _target_from_action(action: str) -> str | None:
    """``"migrate-to sprout_audit.db"`` -> ``"sprout_audit.db"``.

    Only SQLite file targets are actionable. Verbs that point at a non-file
    authority (``"migrate-to derived context index"``) return ``None`` so the
    caller falls back to conservative archiving instead of inventing a target.
    """
    for verb in _VERBS:
        if action.startswith(verb):
            rest = action[len(verb) :].strip()
            if not rest:
                return None
            head = rest.split()[0]
            return head if head.endswith(".db") else None
    return None


def _tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [row[0] for row in rows]


def _table_plan(src: sqlite3.Connection, dst: sqlite3.Connection) -> list[dict[str, Any]]:
    """Row moves for tables present in both databases (column intersection)."""
    dst_tables = set(_tables(dst))
    moves: list[dict[str, Any]] = []
    for table in _tables(src):
        if table not in dst_tables:
            continue
        src_cols = [row[1] for row in src.execute(f'PRAGMA table_info("{table}")')]
        dst_cols = {row[1] for row in dst.execute(f'PRAGMA table_info("{table}")')}
        cols = [c for c in src_cols if c in dst_cols]
        if not cols:
            continue
        count = src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if not count:
            continue
        moves.append({"table": table, "columns": cols, "rows": count})
    return moves


def _backup(paths: list[Path], stamp: str, archive_root: Path) -> Path:
    dest = archive_root / f"pre-migrate-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for base in paths:
        for suffix in _SQLITE_SUFFIXES:
            candidate = base.with_name(base.name + suffix)
            if candidate.exists():
                shutil.copy2(candidate, dest / candidate.name)
    return dest


def _archive_source(name: str, data_root: Path, archive_root: Path) -> None:
    legacy = archive_root / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    for suffix in _SQLITE_SUFFIXES:
        src = data_root / (name + suffix)
        if src.exists():
            shutil.move(str(src), str(legacy / src.name))


def run_migration(
    *, apply: bool = False, data_root: Path | None = None
) -> dict[str, Any]:
    """Carry out every non-active disposition in ``STORAGE_DATABASES``.

    Returns a JSON-serialisable report. With ``apply=False`` (the default) the
    report is computed but nothing on disk is touched.
    """
    root = data_root or _SPROUT_DATA
    archive_root = root / "archive"
    entries: list[dict[str, Any]] = []
    pending: list[tuple[str, str, list[dict[str, Any]]]] = []

    for disposition in STORAGE_DATABASES:
        source = disposition.filename
        src_path = root / source
        if disposition.status == "active" or not src_path.exists():
            continue

        target = _target_from_action(disposition.action)
        if target is None:
            # ``delete`` / undocumented verbs: archive conservatively, keep data.
            entries.append(
                {
                    "source": source,
                    "target": "",
                    "status": "planned" if apply else "would-archive",
                    "details": [f"action={disposition.action}", "archive only (no delete)"],
                }
            )
            pending.append((source, "", []))
            continue

        dst_path = root / target
        if not dst_path.exists():
            entries.append(
                {
                    "source": source,
                    "target": target,
                    "status": "skipped",
                    "details": ["target authority not found"],
                }
            )
            continue

        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        dst = sqlite3.connect(f"file:{dst_path}?mode=ro", uri=True)
        try:
            moves = _table_plan(src, dst)
        finally:
            src.close()
            dst.close()

        details = [f"{m['table']}: {m['rows']} rows -> {len(m['columns'])} cols" for m in moves]
        if not moves:
            details = ["no overlapping rows (already rehomed or empty)"]
        entries.append(
            {
                "source": source,
                "target": target,
                "status": "planned" if apply else "would-migrate",
                "details": details,
            }
        )
        pending.append((source, target, moves))

    if not apply or not pending:
        return {"applied": False, "backup": None, "entries": entries}

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_bases = [root / s for s, _, _ in pending]
    backup_bases += [root / t for _, t, _ in pending if t]
    backup_dir = _backup(sorted(set(backup_bases)), stamp, archive_root)

    for source, target, moves in pending:
        if target and moves:
            src = sqlite3.connect(str(root / source), timeout=15)
            dst = sqlite3.connect(str(root / target), timeout=15)
            try:
                for move in moves:
                    cols = move["columns"]
                    rows = src.execute(
                        f'SELECT {",".join(cols)} FROM "{move["table"]}"'
                    ).fetchall()
                    dst.executemany(
                        f'INSERT OR IGNORE INTO "{move["table"]}" '
                        f'({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                        rows,
                    )
                dst.commit()
            finally:
                src.close()
                dst.close()
        _archive_source(source, root, archive_root)

    for entry in entries:
        if entry["status"] == "planned":
            entry["status"] = "migrated" if entry["target"] else "archived"

    return {"applied": True, "backup": str(backup_dir), "entries": entries}

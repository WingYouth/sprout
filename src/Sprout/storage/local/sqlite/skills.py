"""SQLite implementation of the skill registry (sprout_audit.db, design §10.2).

The table sits beside ``approvals`` in the audit authority so "who approved this
skill" is a JOIN away. Schema creation follows the house pattern: a ``SCHEMA``
constant applied idempotently on open.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from Sprout.skills.models import SkillRecord, TrustLevel
from Sprout.storage.local.sqlite.driver import SqliteDatabase, SqlitePragmas

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    version     TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT 'local',
    origin      TEXT NOT NULL DEFAULT '',
    digest      TEXT NOT NULL DEFAULT '',
    trust       TEXT NOT NULL DEFAULT 'untrusted',
    enabled     INTEGER NOT NULL DEFAULT 1,
    pinned      INTEGER NOT NULL DEFAULT 0,
    path        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT '',
    install_command     TEXT NOT NULL DEFAULT '',
    requires_cli_json   TEXT NOT NULL DEFAULT '[]',
    cli_install_command TEXT NOT NULL DEFAULT '',
    menu_path_json      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source, enabled);
CREATE INDEX IF NOT EXISTS idx_skills_trust  ON skills(trust, enabled);
"""

#: Columns added after the table first shipped; applied idempotently on open, the
#: same way ``SqliteOperationalStore._migrate_approvals`` backfills ``approvals``.
_SKILL_COLUMNS: dict[str, str] = {
    "install_command": "ALTER TABLE skills ADD COLUMN install_command TEXT NOT NULL DEFAULT ''",
    "requires_cli_json": (
        "ALTER TABLE skills ADD COLUMN requires_cli_json TEXT NOT NULL DEFAULT '[]'"
    ),
    "cli_install_command": (
        "ALTER TABLE skills ADD COLUMN cli_install_command TEXT NOT NULL DEFAULT ''"
    ),
    "menu_path_json": (
        "ALTER TABLE skills ADD COLUMN menu_path_json TEXT NOT NULL DEFAULT '[]'"
    ),
}

_COLUMNS = (
    "name, version, description, tags_json, source, origin, digest, trust, "
    "enabled, pinned, path, created_at, updated_at, "
    "install_command, requires_cli_json, cli_install_command, menu_path_json"
)


class SqliteSkillStore:
    """SQLite-backed :class:`~Sprout.storage.contracts.skills.SkillStore`."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Backfill the distribution columns on registries created before §7.5."""
        rows = self._db.fetchall_sync("PRAGMA table_info(skills)")
        existing = {row["name"] for row in rows} if rows else set()
        for column, statement in _SKILL_COLUMNS.items():
            if column not in existing:
                self._db.execute_sync(statement)

    def close(self) -> None:
        self._db.close()

    async def upsert(self, record: SkillRecord) -> None:
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            f"INSERT INTO skills ({_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "version = excluded.version, description = excluded.description, "
            "tags_json = excluded.tags_json, source = excluded.source, "
            "origin = excluded.origin, digest = excluded.digest, "
            "trust = excluded.trust, enabled = excluded.enabled, "
            "pinned = excluded.pinned, path = excluded.path, "
            "updated_at = excluded.updated_at, "
            "install_command = excluded.install_command, "
            "requires_cli_json = excluded.requires_cli_json, "
            "cli_install_command = excluded.cli_install_command, "
            "menu_path_json = excluded.menu_path_json",
            (
                record.name,
                record.version,
                record.description,
                json.dumps(list(record.tags), ensure_ascii=False),
                record.source,
                record.origin,
                record.digest,
                record.trust,
                int(record.enabled),
                int(record.pinned),
                record.path,
                now,
                record.updated_at,
                record.install_command,
                json.dumps(list(record.requires_cli), ensure_ascii=False),
                record.cli_install_command,
                json.dumps(list(record.menu_path), ensure_ascii=False),
            ),
        )

    async def get(self, name: str) -> SkillRecord | None:
        row = await self._db.fetchone(
            f"SELECT {_COLUMNS} FROM skills WHERE name = ?", (name,)
        )
        return _row_to_record(row) if row is not None else None

    async def list(
        self,
        *,
        source: str | None = None,
        trust: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if trust is not None:
            clauses.append("trust = ?")
            params.append(trust)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self._db.fetchall(
            f"SELECT {_COLUMNS} FROM skills{where} ORDER BY name", tuple(params)
        )
        return [_row_to_record(row) for row in rows]

    async def set_enabled(self, name: str, enabled: bool) -> None:
        await self._db.execute(
            "UPDATE skills SET enabled = ?, updated_at = ? WHERE name = ?",
            (int(enabled), datetime.now(UTC).isoformat(), name),
        )

    async def set_trust(self, name: str, trust: str) -> None:
        await self._db.execute(
            "UPDATE skills SET trust = ?, updated_at = ? WHERE name = ?",
            (trust, datetime.now(UTC).isoformat(), name),
        )

    async def remove(self, name: str) -> None:
        await self._db.execute("DELETE FROM skills WHERE name = ?", (name,))

    async def is_trusted(self, name: str, digest: str) -> bool:
        found = await self._db.scalar(
            "SELECT 1 FROM skills WHERE name = ? AND trust = ? AND digest = ? LIMIT 1",
            (name, TrustLevel.TRUSTED.value, digest),
        )
        return found is not None


def _row_to_record(row: Any) -> SkillRecord:
    return SkillRecord(
        name=row["name"],
        version=row["version"],
        description=row["description"],
        tags=tuple(json.loads(row["tags_json"] or "[]")),
        source=row["source"],
        origin=row["origin"],
        digest=row["digest"],
        trust=row["trust"],
        enabled=bool(row["enabled"]),
        pinned=bool(row["pinned"]),
        path=row["path"],
        updated_at=row["updated_at"],
        install_command=row["install_command"] or "",
        requires_cli=tuple(json.loads(row["requires_cli_json"] or "[]")),
        cli_install_command=row["cli_install_command"] or "",
        menu_path=tuple(json.loads(row["menu_path_json"] or "[]")),
    )


def open_skill_store(path: str, pragmas: SqlitePragmas | None = None) -> SqliteSkillStore:
    """Open (and reserve) a skill registry at ``path``, creating the schema if needed."""
    return SqliteSkillStore(SqliteDatabase.open(path, pragmas))

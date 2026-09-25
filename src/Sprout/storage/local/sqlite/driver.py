"""Async SQLite driver: single writer, pooled readers, validated WAL.

One database file is served by exactly one write connection — every write is
serialized through a lock, which makes it the de-facto "single writer queue" —
plus a small pool of read-only connections that never block the writer under
WAL. The pragmas that matter for multi-process safety are applied on open and
the WAL result is *validated*: when WAL cannot be enabled (network filesystems)
the driver falls back to DELETE journaling and logs a loud warning instead of
silently running without it.

Use :meth:`SqliteDatabase.open` so a file path maps to exactly one instance
per process; two stores pointed at the same file must never open two
connections to it.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Sprout.storage.sqlite")

_VALID_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}


@dataclass(frozen=True, slots=True)
class SqlitePragmas:
    """Tunables applied to every connection of a database."""

    busy_timeout_ms: int = 5000
    synchronous: str = "NORMAL"
    wal_autocheckpoint: int = 1000
    mmap_size: int = 268435456
    readers: int = 2


@dataclass(frozen=True, slots=True)
class SqliteCapabilities:
    """What the linked SQLite library can do (FTS5, trigram, WAL)."""

    sqlite_version: str
    fts5: bool
    trigram: bool
    wal: bool


def detect_sqlite_capabilities() -> SqliteCapabilities:
    """Probe the linked SQLite library; never raises."""
    version = sqlite3.sqlite_version
    fts5 = False
    trigram = False
    wal = False
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t_fts USING fts5(x)")
            fts5 = True
            try:
                conn.execute("DROP TABLE t_fts")
                conn.execute(
                    "CREATE VIRTUAL TABLE t_tri USING fts5(x, tokenize='trigram')"
                )
                trigram = True
            except sqlite3.Error:
                trigram = False
        except sqlite3.Error:
            fts5 = False
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        wal = bool(row and str(row[0]).lower() == "wal")
        conn.close()
    except sqlite3.Error:  # pragma: no cover - sqlite itself is broken
        pass
    return SqliteCapabilities(
        sqlite_version=version, fts5=fts5, trigram=trigram, wal=wal
    )


class SqliteDatabase:
    """One database file: one write connection plus a pool of read connections."""

    _shared: dict[str, SqliteDatabase] = {}
    _shared_lock = threading.Lock()

    def __init__(
        self,
        path: str | Path,
        pragmas: SqlitePragmas | None = None,
    ) -> None:
        self._pragmas = pragmas or SqlitePragmas()
        self._memory = str(path) == ":memory:" or str(path).startswith("file::memory:")
        file_path = Path(path)
        if not self._memory and file_path.parent != Path("."):
            file_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(file_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.journal_mode = self._apply_pragmas(self._conn, validate_wal=True)
        self._lock = threading.Lock()
        self._refcount = 0
        self._registry_key: str | None = None
        self._readers: list[tuple[sqlite3.Connection, threading.Lock]] = []
        self._reader_index = 0
        if not self._memory:
            self._open_readers(str(file_path))

    # -- shared-instance registry -----------------------------------------
    @classmethod
    def open(
        cls, path: str | Path, pragmas: SqlitePragmas | None = None
    ) -> SqliteDatabase:
        """Return the shared instance for ``path``, creating it on first use.

        Instances are reference-counted: :meth:`close` only really closes the
        connections when the last user lets go. ``:memory:`` databases are
        never shared.
        """
        if str(path) == ":memory:" or str(path).startswith("file::memory:"):
            return cls(path, pragmas)
        key = str(Path(path).resolve())
        with cls._shared_lock:
            db = cls._shared.get(key)
            if db is None:
                db = cls(path, pragmas)
                db._registry_key = key
                cls._shared[key] = db
            db._refcount += 1
            return db

    @classmethod
    def shared_connection_count(cls, path: str | Path) -> int:
        """Diagnostic: is there a shared instance for ``path`` (0 or 1)?"""
        key = str(Path(path).resolve())
        with cls._shared_lock:
            return 1 if key in cls._shared else 0

    def _apply_pragmas(self, conn: sqlite3.Connection, *, validate_wal: bool) -> str:
        pragmas = self._pragmas
        synchronous = pragmas.synchronous.upper()
        if synchronous not in _VALID_SYNCHRONOUS:
            synchronous = "NORMAL"
        journal_mode = "delete"
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        actual = str(row[0]).lower() if row else ""
        if actual == "wal":
            journal_mode = "wal"
        else:
            conn.execute("PRAGMA journal_mode=DELETE")
            if validate_wal:
                logger.warning(
                    "WAL unavailable for %s (got %r); falling back to DELETE "
                    "journaling. Concurrent access will be limited — this is "
                    "expected on network filesystems.",
                    self.path,
                    actual,
                )
        conn.execute(f"PRAGMA busy_timeout={int(pragmas.busy_timeout_ms)}")
        conn.execute(f"PRAGMA synchronous={synchronous}")
        conn.execute(f"PRAGMA wal_autocheckpoint={int(pragmas.wal_autocheckpoint)}")
        conn.execute(f"PRAGMA mmap_size={int(pragmas.mmap_size)}")
        conn.execute("PRAGMA foreign_keys=ON")
        return journal_mode

    def _open_readers(self, file_path: str) -> None:
        for _ in range(max(1, self._pragmas.readers)):
            try:
                conn = sqlite3.connect(
                    f"file:{file_path}?mode=ro", uri=True, check_same_thread=False
                )
            except sqlite3.Error:
                conn = sqlite3.connect(file_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._apply_pragmas(conn, validate_wal=False)
            self._readers.append((conn, threading.Lock()))

    @property
    def path(self) -> str:
        return self._conn.execute("PRAGMA database_list").fetchone()[2]

    # -- schema / writes -----------------------------------------------------
    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)
            self._conn.commit()

    async def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> int:
        return await asyncio.to_thread(self._sync_execute, sql, parameters)

    async def execute_batch(
        self, statements: Iterable[tuple[str, tuple[Any, ...]]]
    ) -> None:
        """Run several statements as one atomic transaction on the writer."""
        await asyncio.to_thread(self._sync_execute_batch, list(statements))

    def execute_sync(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        """Blocking variant used by schema migrations in synchronous constructors."""
        self._sync_execute(sql, parameters)

    def _sync_execute(self, sql: str, parameters: tuple[Any, ...]) -> int:
        with self._lock:
            cursor = self._conn.execute(sql, parameters)
            changed = cursor.rowcount
            self._conn.commit()
            return changed

    def _sync_execute_batch(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for sql, parameters in statements:
                    self._conn.execute(sql, parameters)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # -- reads ----------------------------------------------------------------
    async def fetchone(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._read, "fetchone", sql, parameters)

    async def fetchall(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._read, "fetchall", sql, parameters)

    async def scalar(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        row = await self.fetchone(sql, parameters)
        return row[0] if row is not None else None

    def fetchone_sync(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        """Blocking read on the writer, for synchronous constructors."""
        with self._lock:
            return self._conn.execute(sql, parameters).fetchone()

    def fetchall_sync(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> list[sqlite3.Row]:
        """Blocking read on the writer, for synchronous constructors."""
        with self._lock:
            return self._conn.execute(sql, parameters).fetchall()

    def _read(
        self, mode: str, sql: str, parameters: tuple[Any, ...]
    ) -> sqlite3.Row | None | list[sqlite3.Row]:
        if not self._readers:
            with self._lock:
                cursor = self._conn.execute(sql, parameters)
                return cursor.fetchone() if mode == "fetchone" else cursor.fetchall()
        self._reader_index = (self._reader_index + 1) % len(self._readers)
        conn, lock = self._readers[self._reader_index]
        with lock:
            cursor = conn.execute(sql, parameters)
            return cursor.fetchone() if mode == "fetchone" else cursor.fetchall()

    # -- diagnostics ----------------------------------------------------------
    def quick_check(self) -> str:
        """Integrity spot-check used by ``sprout storage status``."""
        with self._lock:
            row = self._conn.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row else "unknown"

    def file_size_bytes(self) -> int:
        path = Path(self.path)
        return path.stat().st_size if path.is_file() else 0

    def wal_size_bytes(self) -> int:
        wal = Path(self.path + "-wal")
        return wal.stat().st_size if wal.is_file() else 0

    def checkpoint(self, mode: str = "TRUNCATE") -> None:
        with self._lock:
            self._conn.execute(f"PRAGMA wal_checkpoint({mode})")

    def backup_to(self, target_path: str | Path) -> None:
        """Online backup into ``target_path`` (safe while serving traffic)."""
        target = sqlite3.connect(str(target_path))
        try:
            with self._lock:
                self._conn.backup(target)
        finally:
            target.close()

    # -- shutdown --------------------------------------------------------------
    def close(self) -> None:
        if self._registry_key is not None:
            with SqliteDatabase._shared_lock:
                self._refcount -= 1
                if self._refcount > 0:
                    return
                SqliteDatabase._shared.pop(self._registry_key, None)
                self._registry_key = None
        self._close_connections()

    def _close_connections(self) -> None:
        if self.journal_mode == "wal":
            try:
                self.checkpoint("TRUNCATE")
            except sqlite3.Error:  # noqa: BLE001 - shutdown must not raise
                pass
        with self._lock:
            self._conn.close()
        for conn, lock in self._readers:
            with lock:
                conn.close()
        self._readers = []

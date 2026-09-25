"""File-system MemoryStore: ``MEMORY.md`` and ``USER.md`` under a home directory.

Layout (mirrors Hermes):

    ~/.hermes/memories/MEMORY.md   # per-session facts, ``§``-separated entries
    ~/.hermes/memories/USER.md     # per-user profile facts

Both files hold *plain markdown*. Each section between the ``§`` delimiter is
one fact; the first line is the key, the rest is the value. Char limits are
enforced on the rendered file (Hermes: 2200 / 1375 chars; Chinese-corrected
in :class:`Sprout.memory.scanner.MemoryScanner`).

Writes are atomic (``tmp + os.replace``); reads are lazy so a missing file
becomes an empty fact list.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from Sprout.memory.contract import MemoryStore
from Sprout.memory.models import SessionFact, SessionSummary, UserFact
from Sprout.memory.scanner import MemoryScanner

_ENTRY_DELIMITER = "§"
_SESSION_DIR = "sessions"


def _render_facts(entries: Iterable[tuple[str, str]]) -> str:
    parts = []
    for key, body in entries:
        if not body:
            parts.append(key)
        else:
            parts.append(f"{key}\n{body}")
    return ("\n" + _ENTRY_DELIMITER + "\n").join(parts)


def _parse_facts(text: str) -> list[tuple[str, str]]:
    """Split a ``§``-delimited file into ``(key, body)`` tuples."""
    text = text.strip()
    if not text:
        return []
    chunks = [c.strip() for c in text.split(_ENTRY_DELIMITER)]
    facts: list[tuple[str, str]] = []
    for chunk in chunks:
        if not chunk:
            continue
        lines = chunk.split("\n", 1)
        key = lines[0].strip()
        body = lines[1].strip() if len(lines) == 2 else ""
        facts.append((key, body))
    return facts


def _summary_to_json(summary: SessionSummary) -> str:
    """Serialise one rolling digest to a single JSONL line."""
    return json.dumps(
        {
            "session_id": summary.session_id,
            "seq": summary.seq,
            "covered_through": summary.covered_through,
            "content": summary.content,
            "created_at": summary.created_at.isoformat(),
        },
        ensure_ascii=False,
    )


def _summary_from_json(line: str) -> SessionSummary:
    """Parse one JSONL line back into a :class:`SessionSummary`."""
    data = json.loads(line)
    return SessionSummary(
        session_id=data["session_id"],
        seq=data["seq"],
        covered_through=data["covered_through"],
        content=data["content"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )


class FileSystemMemoryStore(MemoryStore):
    """Curated facts stored as two markdown files under ``home``."""

    def __init__(self, home: str | Path) -> None:
        self._home = Path(home)
        self._home.mkdir(parents=True, exist_ok=True)
        self._memory_path = self._home / "MEMORY.md"
        self._user_path = self._home / "USER.md"
        self._sessions_dir = self._home / _SESSION_DIR
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._scanner = MemoryScanner()
        self._locks: dict[Path, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @property
    def home(self) -> Path:
        return self._home

    # -- internal helpers ------------------------------------------------------
    def _lock_for(self, path: Path) -> asyncio.Lock:
        lock = self._locks.get(path)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[path] = lock
        return lock

    async def _read(self, path: Path) -> str:
        return await asyncio.to_thread(self._read_sync, path)

    @staticmethod
    def _read_sync(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def _write(self, path: Path, content: str) -> None:
        async with self._global_lock, self._lock_for(path):
            await asyncio.to_thread(self._write_sync, path, content)

    @staticmethod
    def _write_sync(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)

    @staticmethod
    def _append_sync(path: Path, line: str) -> None:
        """Append one JSONL record; the file is created on first write."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _session_path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe}.md"

    def _summary_path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe}.summary.jsonl"

    # -- session facts ---------------------------------------------------------
    async def list_session_facts(self, session_id: str) -> list[SessionFact]:
        text = await self._read(self._session_path(session_id))
        now = datetime.now(UTC)
        return [
            SessionFact(
                session_id=session_id,
                key=key,
                value=body,
                updated_at=now,
            )
            for key, body in _parse_facts(text)
        ]

    async def add_session_fact(
        self, fact: SessionFact, *, char_limit: int
    ) -> SessionFact | None:
        scan = self._scanner.scan(fact.value)
        if not scan.accepted:
            return fact  # rejected; caller surfaces the reason
        path = self._session_path(fact.session_id)
        current = _parse_facts(await self._read(path))
        existing_chars = sum(len(k) + len(v) + 4 for k, v in current)
        addition_chars = len(fact.key) + len(fact.value) + 4
        if existing_chars + addition_chars > char_limit:
            return fact  # cap hit; caller consolidates
        current.append((fact.key, fact.value))
        await self._write(path, _render_facts(current))
        return None

    async def replace_session_fact(
        self,
        session_id: str,
        old_text: str,
        new_fact: SessionFact,
        *,
        char_limit: int,
    ) -> bool:
        scan = self._scanner.scan(new_fact.value)
        if not scan.accepted:
            return False
        path = self._session_path(session_id)
        current = _parse_facts(await self._read(path))
        matches = [
            (i, k, v) for i, (k, v) in enumerate(current)
            if old_text in k or old_text in v
        ]
        if not matches:
            return False
        existing_chars = sum(len(k) + len(v) + 4 for k, v in current)
        delta = len(new_fact.key) + len(new_fact.value) - sum(
            len(k) + len(v) for _, k, v in matches
        )
        if existing_chars + delta > char_limit:
            return False
        for i, _, _ in reversed(matches):
            current[i] = (new_fact.key, new_fact.value)
        await self._write(path, _render_facts(current))
        return True

    async def remove_session_fact(self, session_id: str, substring: str) -> int:
        path = self._session_path(session_id)
        current = _parse_facts(await self._read(path))
        kept = [
            (k, v) for k, v in current
            if substring not in k and substring not in v
        ]
        if len(kept) == len(current):
            return 0
        await self._write(path, _render_facts(kept))
        return len(current) - len(kept)

    # -- rolling summary -------------------------------------------------------
    async def latest_session_summary(self, session_id: str) -> SessionSummary | None:
        text = await self._read(self._summary_path(session_id))
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        return _summary_from_json(lines[-1])

    async def save_session_summary(self, summary: SessionSummary) -> None:
        path = self._summary_path(summary.session_id)
        async with self._global_lock, self._lock_for(path):
            await asyncio.to_thread(self._append_sync, path, _summary_to_json(summary))

    # -- user facts ------------------------------------------------------------
    async def list_user_facts(self, user_id: str) -> list[UserFact]:
        text = await self._read(self._user_path)
        now = datetime.now(UTC)
        return [
            UserFact(user_id=user_id, key=k, value=v, updated_at=now)
            for k, v in _parse_facts(text)
        ]

    async def add_user_fact(
        self, fact: UserFact, *, char_limit: int
    ) -> UserFact | None:
        scan = self._scanner.scan(fact.value)
        if not scan.accepted:
            return fact
        current = _parse_facts(await self._read(self._user_path))
        existing_chars = sum(len(k) + len(v) + 4 for k, v in current)
        addition_chars = len(fact.key) + len(fact.value) + 4
        if existing_chars + addition_chars > char_limit:
            return fact
        current.append((fact.key, fact.value))
        await self._write(self._user_path, _render_facts(current))
        return None

    async def replace_user_fact(
        self,
        user_id: str,
        old_text: str,
        new_fact: UserFact,
        *,
        char_limit: int,
    ) -> bool:
        scan = self._scanner.scan(new_fact.value)
        if not scan.accepted:
            return False
        current = _parse_facts(await self._read(self._user_path))
        matches = [
            (i, k, v) for i, (k, v) in enumerate(current)
            if old_text in k or old_text in v
        ]
        if not matches:
            return False
        existing_chars = sum(len(k) + len(v) + 4 for k, v in current)
        delta = len(new_fact.key) + len(new_fact.value) - sum(
            len(k) + len(v) for _, k, v in matches
        )
        if existing_chars + delta > char_limit:
            return False
        for i, _, _ in reversed(matches):
            current[i] = (new_fact.key, new_fact.value)
        await self._write(self._user_path, _render_facts(current))
        return True

    async def remove_user_fact(self, user_id: str, substring: str) -> int:
        current = _parse_facts(await self._read(self._user_path))
        kept = [(k, v) for k, v in current if substring not in k and substring not in v]
        if len(kept) == len(current):
            return 0
        await self._write(self._user_path, _render_facts(kept))
        return len(current) - len(kept)

    # -- snapshot --------------------------------------------------------------
    async def snapshot_version(self) -> str:
        memory = await self._read(self._memory_path)
        user = await self._read(self._user_path)
        sessions = ""
        for path in sorted(self._sessions_dir.glob("*.md")):
            sessions += await self._read(path)
        digest = hashlib.sha256(
            f"{memory}\u241F{user}\u241F{sessions}".encode()
        ).hexdigest()
        return digest

    def close(self) -> None:
        return None
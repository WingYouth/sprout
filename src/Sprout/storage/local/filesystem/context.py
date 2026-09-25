"""JSONL context store: context compositions as an append-only evidence log.

Each session gets its own ``<session_id>.jsonl`` file under the configured
directory, so rotation and replay stay per-session. Search is a linear scan
over the log — the JSONL lane is the *evidence* authority, not a query
engine; semantic and full-text lookups belong to the derived lanes.
"""

from __future__ import annotations

import json
from pathlib import Path

from Sprout.storage.contracts.context import ContextRecord


class JsonlContextStore:
    """Append-only context snapshots, one JSONL file per session."""

    def __init__(self, directory: str | Path) -> None:
        self._root = Path(directory)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._root / f"{safe}.jsonl"

    async def append(self, record: ContextRecord) -> None:
        path = self._path(record.session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record.to_json(), ensure_ascii=False, default=str) + "\n"
            )

    async def latest(self, session_id: str) -> ContextRecord | None:
        records = await self.list_records(session_id, limit=1)
        return records[-1] if records else None

    async def list_records(
        self, session_id: str, *, limit: int = 20
    ) -> list[ContextRecord]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        records: list[ContextRecord] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(ContextRecord.from_json(json.loads(line)))
        return records[-limit:]

    async def search(self, query: str, *, limit: int = 10) -> list[ContextRecord]:
        """Linear substring scan; ranked nowhere, honest everywhere."""
        hits: list[ContextRecord] = []
        needle = query.lower()
        for path in sorted(self._root.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or needle not in line.lower():
                        continue
                    hits.append(ContextRecord.from_json(json.loads(line)))
                    if len(hits) >= limit:
                        return hits
        return hits

    async def count(self) -> int:
        total = 0
        for path in self._root.glob("*.jsonl"):
            with path.open(encoding="utf-8") as handle:
                total += sum(1 for line in handle if line.strip())
        return total


__all__ = ["JsonlContextStore"]

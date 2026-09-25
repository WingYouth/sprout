"""A skill source backed by a catalog manifest (design §7.3).

The manifest is a JSON document listing available skills::

    {"skills": [{"name": "pdf", "description": "fill forms",
                 "version": "1.0", "tags": ["pdf"],
                 "url": "https://example.test/pdf/SKILL.md"}]}

``url`` may be a plain path, ``file://``, or ``http(s)://``. Fetching is bounded
and never executes anything.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.sources.local import _tokens

MAX_FETCH_BYTES = 1_000_000


class CatalogSource:
    """Searches a JSON catalog and fetches entries by URL."""

    def __init__(
        self,
        manifest: str,
        *,
        name: str = "catalog",
        source: str = "catalog",
        max_bytes: int = MAX_FETCH_BYTES,
        timeout: float = 10.0,
    ) -> None:
        self.name = name
        self._manifest = manifest
        self._source = source
        self._max_bytes = max_bytes
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        wanted = _tokens(query)
        hits: list[tuple[float, SkillStub]] = []
        for entry in self._entries():
            stub = self._stub(entry)
            haystack = _tokens(" ".join((stub.name, stub.description, *stub.tags)))
            overlap = wanted & haystack
            if not overlap:
                continue
            hits.append((float(len(overlap)), stub))
        hits.sort(key=lambda item: (-item[0], item[1].name))
        return [stub for _, stub in hits[:limit]]

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        data = self._read(stub.origin)
        return SkillBundle(
            stub=stub,
            files={"SKILL.md": data},
            script_text=data.decode("utf-8", errors="replace"),
        )

    # -- internals ---------------------------------------------------------

    def _entries(self) -> list[dict[str, object]]:
        try:
            raw = json.loads(self._read(self._manifest).decode("utf-8"))
        except (OSError, ValueError):
            return []
        entries = raw.get("skills", []) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)]

    def _stub(self, entry: dict[str, object]) -> SkillStub:
        tags = entry.get("tags", [])
        requires_cli = entry.get("requires_cli", [])
        return SkillStub(
            name=str(entry.get("name", "")),
            source=self._source,
            origin=str(entry.get("url", "")),
            description=str(entry.get("description", "")),
            version=str(entry.get("version", "")),
            tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
            digest=str(entry.get("digest", "")),
            install_command=str(entry.get("install_command", "")),
            requires_cli=(
                tuple(str(binary) for binary in requires_cli)
                if isinstance(requires_cli, list)
                else ()
            ),
            cli_install_command=str(entry.get("cli_install_command", "")),
        )

    def _read(self, location: str) -> bytes:
        parsed = urlparse(location)
        if parsed.scheme in {"http", "https"}:
            with urllib.request.urlopen(location, timeout=self._timeout) as response:
                return response.read(self._max_bytes)
        path = Path(parsed.path if parsed.scheme == "file" else location)
        return path.read_bytes()[: self._max_bytes]

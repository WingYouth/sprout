"""Well-known skill source (design §7.3): ``<site>/.well-known/skills/index.json``."""

from __future__ import annotations

import json
from urllib.parse import urljoin

from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.sources.cli import CliRunner, SubprocessRunner, fetch_url_as_dir

INDEX_SUFFIX = ".well-known/skills/index.json"


def index_url_for(site: str) -> str:
    """``https://example.com`` -> ``https://example.com/.well-known/skills/index.json``."""
    base = site if site.endswith("/") else site + "/"
    return urljoin(base, INDEX_SUFFIX)


class WellKnownSource:
    """Discover skills from a site's ``.well-known/skills/index.json`` via ``curl``."""

    name = "well-known"

    def __init__(self, *, runner: CliRunner | None = None, timeout: float = 60.0) -> None:
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        site = query.strip()
        if not site.lower().startswith(("http://", "https://")):
            raise ValueError(f"expected an http(s) site URL, got {query!r}")
        url = index_url_for(site)
        result = await self._runner.run(["curl", "-fsSL", url], timeout=self._timeout)
        if not result.ok:
            return []
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            return []
        entries = payload.get("skills") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            return []
        stubs: list[SkillStub] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            skill_url = entry.get("url") or urljoin(url, f"{entry['name']}/SKILL.md")
            stubs.append(
                SkillStub(
                    name=str(entry["name"]),
                    source=self.name,
                    origin=str(skill_url),
                    description=str(entry.get("description", "")),
                    version=str(entry.get("version", "")),
                    tags=tuple(entry.get("tags") or ()),
                )
            )
            if len(stubs) >= limit:
                break
        return stubs

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        return await fetch_url_as_dir(
            self._runner, stub.origin, name=stub.name, source=self.name, timeout=self._timeout
        )

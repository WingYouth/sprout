"""Direct-URL skill source (design §7.3): a ``SKILL.md`` fetched over the CLI."""

from __future__ import annotations

from urllib.parse import urlparse

from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.sources.cli import CliRunner, SubprocessRunner, fetch_url_as_dir


def skill_name_from_url(url: str) -> str:
    """Best-effort skill name from a ``SKILL.md`` URL (``.../pdf/SKILL.md`` -> ``pdf``)."""
    path = urlparse(url).path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "skill"
    last = parts[-1]
    if last.lower() in {"skill.md", "index.md"}:
        return (parts[-2] if len(parts) >= 2 else "skill").removesuffix(".md") or "skill"
    return last.removesuffix(".md") or "skill"


class UrlSource:
    """Fetch a single skill from a direct ``SKILL.md`` URL using ``curl``."""

    name = "url"

    def __init__(self, *, runner: CliRunner | None = None, timeout: float = 60.0) -> None:
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        url = query.strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"expected an http(s) URL, got {query!r}")
        return [
            SkillStub(
                name=skill_name_from_url(url),
                source=self.name,
                origin=url,
                description=f"URL: {url}",
            )
        ][:limit]

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        return await fetch_url_as_dir(
            self._runner, stub.origin, name=stub.name, source=self.name, timeout=self._timeout
        )

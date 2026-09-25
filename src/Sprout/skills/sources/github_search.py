"""Discovering skill repositories on GitHub without any configuration (§7.6).

This is what makes discovery work out of the box: the operator does not have to
curate a list of sites first. It searches GitHub for repositories that look like
they publish skills, then **verifies** each candidate really contains a
``SKILL.md`` before believing it.

That verification step is not optional. GitHub's repository search matches
free text loosely, so ``q=SKILL.md`` happily returns repositories that merely
mention the string — a measured run put ``wechatDownload`` in the first page. A
repository name is a hint, never evidence.

Two constraints shape the design:

* **The unauthenticated search API allows 10 requests/minute**, which is easy to
  exceed. A ``GITHUB_TOKEN`` in the environment raises that to 30 searches/min
  (5000 core requests/hour) and is used automatically when present; without it
  the client backs off on 403 and reports the reason instead of failing silently.
* **Code search cannot be used** — ``/search/code`` requires authentication, so
  finding skills means listing a repository's tree via the contents API, which
  is unauthenticated.

Nothing here installs or executes anything: it returns
:class:`~Sprout.skills.sources.base.SkillStub` candidates, and an
``install_command`` read from a fetched document is carried as text for a human
to look at (see ``crawler.py``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from Sprout.skills.loader import load_standard_skill
from Sprout.skills.sources.base import SkillStub

logger = logging.getLogger("sprout.skills")

GITHUB_API = "https://api.github.com"

#: Queries run together and merged (decision: "multiple queries, merged"). Each
#: targets a different way a skill repository announces itself, so no single
#: query shape has to be perfect. Topics carry the least noise; ``SKILL.md``
#: carries the widest net and relies on verification to filter.
DEFAULT_QUERIES: tuple[str, ...] = (
    "topic:claude-skills",
    "topic:agent-skills",
    "SKILL.md in:name,description,readme",
)

#: Where a skill document may sit inside a repository, in the order we look.
_SKILL_PATHS: tuple[str, ...] = ("SKILL.md", "skills", "src", ".claude/skills")


@dataclass(frozen=True, slots=True)
class GitHubSearchResult:
    """What one discovery pass found, plus why anything was skipped."""

    stubs: tuple[SkillStub, ...] = ()
    errors: tuple[str, ...] = ()
    truncated: bool = False


@dataclass
class _RateLimit:
    """Tracks the anonymous search budget so we stop before burning it."""

    remaining: int = 10
    exhausted: bool = False
    notes: list[str] = field(default_factory=list)


class GitHubSkillSearch:
    """Repository search + SKILL.md verification (design §7.6).

    ``fetch`` is injectable so tests run without touching the network.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        queries: tuple[str, ...] = DEFAULT_QUERIES,
        per_query: int = 5,
        max_results: int = 5,
        timeout: float = 15.0,
        max_verify: int = 8,
        fetch: Any | None = None,
    ) -> None:
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._queries = queries
        self._per_query = per_query
        self._max_results = max_results
        self._timeout = timeout
        self._max_verify = max_verify
        self._fetch = fetch or self._http_get

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    async def search(self, query: str = "") -> GitHubSearchResult:
        """Find skill repositories, verified to actually contain a ``SKILL.md``.

        ``query`` narrows the free-text query slightly, but discovery stays
        topic-driven: a repository that publishes skills rarely names the task it
        solves, so a pure keyword search would miss most of them.
        """
        errors: list[str] = []
        repos: list[str] = []
        seen: set[str] = set()

        for github_query in self._queries:
            try:
                found = await self._search_repos(github_query)
            except PermissionError as exc:
                # Rate limited: report it once and stop asking, rather than
                # hammering a budget that is already gone.
                errors.append(str(exc))
                break
            except Exception as exc:
                logger.debug("GitHub query %r failed: %s", github_query, exc)
                errors.append(f"{github_query}: {exc}")
                continue
            for name in found:
                if name not in seen:
                    seen.add(name)
                    repos.append(name)

        stubs: list[SkillStub] = []
        for repo in repos[: self._max_verify]:
            if len(stubs) >= self._max_results:
                break
            try:
                stubs.extend(await self._skills_in_repo(repo))
            except Exception as exc:
                logger.debug("Verifying %s failed: %s", repo, exc)
                errors.append(f"{repo}: {exc}")

        if query.strip():
            stubs = _matching(stubs, query)
        return GitHubSearchResult(
            stubs=tuple(stubs[: self._max_results]),
            errors=tuple(errors),
            truncated=len(repos) > self._max_verify,
        )

    # -- search ------------------------------------------------------------

    async def _search_repos(self, query: str) -> list[str]:
        """One repository search; returns ``owner/name`` slugs."""
        params = urllib.parse.urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": self._per_query}
        )
        payload = await self._get_json(f"{GITHUB_API}/search/repositories?{params}")
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        return [
            str(item["full_name"])
            for item in items
            if isinstance(item, dict) and item.get("full_name")
        ]

    async def _skills_in_repo(self, repo: str) -> list[SkillStub]:
        """Every ``SKILL.md`` this repository actually publishes.

        This is the verification half: a repository that does not contain a
        readable skill document contributes nothing, however well it matched the
        search query.
        """
        stubs: list[SkillStub] = []
        for path in await self._skill_paths(repo):
            document = await self._skill_document(repo, path)
            if document is None:
                continue
            stub = _parse_stub(document, repo=repo, path=path)
            if stub is not None:
                stubs.append(stub)
        return stubs

    async def _skill_paths(self, repo: str) -> list[str]:
        """Candidate ``SKILL.md`` paths, from the repository tree.

        Prefers a single tree listing over probing fixed guesses, so a repository
        that keeps skills somewhere unusual is still discovered.
        """
        tree = await self._get_json(f"{GITHUB_API}/repos/{repo}/git/trees/HEAD?recursive=1")
        entries = tree.get("tree") if isinstance(tree, dict) else None
        if isinstance(entries, list):
            paths = [
                str(entry["path"])
                for entry in entries
                if isinstance(entry, dict)
                and str(entry.get("path", "")).lower().endswith("skill.md")
            ]
            if paths:
                return paths[: self._max_verify]

        # Fall back to the conventional locations for repositories whose tree is
        # too large for the API to return in one page.
        contents = await self._get_json(f"{GITHUB_API}/repos/{repo}/contents/")
        if not isinstance(contents, list):
            return []
        names = {
            str(entry.get("name", ""))
            for entry in contents
            if isinstance(entry, dict)
        }
        paths: list[str] = []
        if "SKILL.md" in names:
            paths.append("SKILL.md")
        for directory in _SKILL_PATHS[1:]:
            if directory.rsplit("/", 1)[-1] in names:
                subs = await self._get_json(
                    f"{GITHUB_API}/repos/{repo}/contents/{directory}"
                )
                if isinstance(subs, list):
                    paths.extend(
                        f"{directory}/{entry['name']}/SKILL.md"
                        for entry in subs
                        if isinstance(entry, dict) and entry.get("type") == "dir"
                    )
        return paths[: self._max_verify]

    async def _skill_document(self, repo: str, path: str) -> str | None:
        """Fetch one ``SKILL.md`` as text, via the contents API."""
        url = f"{GITHUB_API}/repos/{repo}/contents/{urllib.parse.quote(path)}"
        payload = await self._get_json(url)
        if not isinstance(payload, dict):
            return None
        content = payload.get("content")
        if not isinstance(content, str):
            return None
        try:
            return base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    # -- transport ---------------------------------------------------------

    async def _get_json(self, url: str) -> Any:
        body = await self._fetch(url)
        try:
            return json.loads(body)
        except ValueError:
            return None

    async def _http_get(self, url: str) -> str:
        """Plain ``urllib`` GET with optional token auth.

        Deliberately not broker-routed (see the module docstring): this runs
        against a fixed API host, never a URL the model chose.
        """
        return await asyncio.to_thread(_read_url, url, self._token, self._timeout)


def _read_url(url: str, token: str, timeout: float) -> str:
    headers = {
        "User-Agent": "sprout-skills",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(1_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            # 403 without a token is GitHub's anonymous rate limit, not a
            # permission problem. Say which, so the fix is obvious.
            hint = (
                "set GITHUB_TOKEN to raise the limit"
                if not token
                else "GitHub rate limit reached"
            )
            raise PermissionError(f"GitHub API rate limited ({exc.code}); {hint}") from exc
        raise
    except TimeoutError as exc:
        raise RuntimeError(f"GitHub request timed out after {timeout}s") from exc


def _parse_stub(document: str, *, repo: str, path: str) -> SkillStub | None:
    """Turn a raw ``SKILL.md`` into a candidate, or ``None`` if it is unusable."""
    import shutil
    import tempfile
    from pathlib import Path

    workdir = Path(tempfile.mkdtemp(prefix="sprout-gh-"))
    target = workdir / "SKILL.md"
    try:
        target.write_text(document, encoding="utf-8")
        skill = load_standard_skill(target)
    except (ValueError, OSError) as exc:
        logger.debug("Unparseable skill in %s at %s: %s", repo, path, exc)
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    origin = f"github:{repo}" + (f"/{directory}" if directory else "")
    return SkillStub(
        name=skill.name,
        source="github",
        origin=origin,
        description=skill.description,
        version=skill.version,
        tags=skill.tags,
        install_command=skill.install_command,
        requires_cli=skill.requires_cli,
        cli_install_command=skill.cli_install_command,
    )


def _matching(stubs: list[SkillStub], query: str) -> list[SkillStub]:
    """Keep stubs whose text overlaps the query at all (crude, but cheap)."""
    from Sprout.skills.sources.local import _tokens

    wanted = _tokens(query)
    if not wanted:
        return stubs
    return [
        stub
        for stub in stubs
        if wanted & _tokens(" ".join((stub.name, stub.description, *stub.tags)))
    ]

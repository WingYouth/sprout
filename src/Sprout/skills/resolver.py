"""Requirement → skill, end to end (design §7.1).

This is the orchestration the design doc calls for and the codebase never had:
the pieces (``SkillMatcher``, the sources, ``SkillInstallBroker``) all existed,
but only the CLI wired them together by hand. :class:`SkillResolver` is the one
place that answers "the user wants X — do we have a skill for it, and if not,
where could we get one?".

The flow is deliberately two-speed:

1. **Local, always, cheap.** Read the ``index.json`` snapshot and score it. No
   network, no disk walk — this runs on every turn.
2. **Remote, only on request.** Crawling configured catalogs is slow and hits
   third-party sites, so it happens on an explicit tool call, never implicitly.

Nothing here installs anything on its own: :meth:`SkillResolver.install` routes
through :class:`~Sprout.skills.broker.SkillInstallBroker`, which scans and defers
to the policy engine (§8.4). The resolver only decides *what to offer*.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.skills.matcher import SkillMatcher
from Sprout.skills.ranker import RankedStub, rank_stubs
from Sprout.skills.sources.base import SkillStub

if TYPE_CHECKING:
    from Sprout.skills.broker import InstallReport, SkillInstallBroker
    from Sprout.skills.index import SkillIndex
    from Sprout.skills.sources.base import SkillSource

logger = logging.getLogger("sprout.skills")


@dataclass(frozen=True, slots=True)
class Resolution:
    """What :meth:`SkillResolver.resolve` found."""

    query: str
    installed: tuple[Any, ...] = ()  # SkillHit; untitled to avoid a cycle
    candidates: tuple[RankedStub, ...] = ()
    crawled: bool = False
    errors: tuple[str, ...] = ()

    @property
    def hit_locally(self) -> bool:
        return bool(self.installed)

    @property
    def empty(self) -> bool:
        return not self.installed and not self.candidates

    def to_text(self) -> str:
        """Render for the model. Explicitly *offers* rather than acts."""
        lines: list[str] = []
        if self.installed:
            lines.append(f"Installed skills matching {self.query!r}:")
            for hit in self.installed:
                record = hit.record
                lines.append(
                    f"- {record.name} (v{record.version}) [{record.trust}] "
                    f"matched on {', '.join(hit.matched_on)}: {record.description}"
                )
        if self.candidates:
            lines.append("Remote candidates (not installed — ask the user first):")
            for ranked in self.candidates:
                stub = ranked.stub
                suffix = f" ({'; '.join(ranked.reasons)})" if ranked.reasons else ""
                lines.append(
                    f"- {stub.name} from {stub.source}{suffix}: {stub.description}"
                )
                if stub.origin:
                    lines.append(f"  origin: {stub.origin}")
                if stub.install_command:
                    # Shown, never run: this string came off the network.
                    lines.append(f"  install with: {stub.install_command}")
                if stub.requires_cli:
                    lines.append(f"  requires CLI: {', '.join(stub.requires_cli)}")
                if stub.cli_install_command:
                    lines.append(f"  CLI install with: {stub.cli_install_command}")
        if not lines:
            note = " (remote catalogs searched)" if self.crawled else ""
            lines.append(f"No skill matching {self.query!r} found{note}.")
        if self.errors:
            lines.append("Source errors: " + "; ".join(self.errors))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Structured result for tool consumers."""
        return {
            "query": self.query,
            "installed": [
                {"name": hit.record.name, "version": hit.record.version, "score": hit.score}
                for hit in self.installed
            ],
            "candidates": [
                {
                    "name": ranked.stub.name,
                    "source": ranked.stub.source,
                    "origin": ranked.stub.origin,
                    "description": ranked.stub.description,
                    "install_command": ranked.stub.install_command,
                    "requires_cli": list(ranked.stub.requires_cli),
                    "cli_install_command": ranked.stub.cli_install_command,
                    "score": ranked.score,
                    "reasons": list(ranked.reasons),
                }
                for ranked in self.candidates
            ],
            "crawled": self.crawled,
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class InstallAttempt:
    """The outcome of asking the broker to install one candidate."""

    ok: bool
    message: str
    approval_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class SkillResolver:
    """Requirement-driven skill lookup and install (design §7.1)."""

    def __init__(
        self,
        *,
        index: SkillIndex,
        sources: Sequence[SkillSource] = (),
        matcher: SkillMatcher | None = None,
        broker: SkillInstallBroker | None = None,
        skills_dir: str | Path = "",
        max_candidates: int = 5,
        on_install: Callable[[], None] | None = None,
    ) -> None:
        self._index = index
        self._sources = tuple(sources)
        self._matcher = matcher or SkillMatcher()
        self._broker = broker
        self._skills_dir = Path(skills_dir) if skills_dir else None
        self._max_candidates = max_candidates
        #: Invoked after a successful install so the caller can refresh whatever
        #: snapshot it holds of the skills directory (the runtime reloads its
        #: registry here, so the new skill is usable without a restart).
        self._on_install = on_install

    @property
    def sources(self) -> tuple[SkillSource, ...]:
        return self._sources

    # -- lookup ----------------------------------------------------------------

    async def resolve(
        self, query: str, *, crawl: bool = False, limit: int | None = None
    ) -> Resolution:
        """Match installed skills; optionally search remote sources too.

        A local hit short-circuits the crawl: if a trusted skill already does the
        job there is no reason to hit the network.
        """
        if not query.strip():
            return Resolution(query=query)

        local = tuple(self._matcher.match(query, self._index, limit=limit or 5))
        if local or not crawl:
            return Resolution(query=query, installed=local)

        # A source whose cache is empty would otherwise report "nothing found"
        # forever, which reads as "the skill does not exist" rather than "nobody
        # has populated the cache yet". Populating it is a network hit, but the
        # caller asked for a crawl explicitly.
        await self._populate_empty_sources()

        candidates, errors = await self._search_sources(query, limit=limit)
        return Resolution(
            query=query,
            installed=local,
            candidates=candidates,
            crawled=True,
            errors=errors,
        )

    async def _populate_empty_sources(self) -> None:
        """Refresh any source that can discover but currently holds nothing.

        Only sources exposing ``refresh`` (the discovery cache) are touched, and
        only when they are empty — a populated cache is served from disk with no
        network at all, which is the common case once ``sprout skills crawl`` has
        been run once.
        """
        for source in self._sources:
            refresh = getattr(source, "refresh", None)
            if refresh is None:
                continue
            try:
                if not await source.search("", limit=1):
                    logger.info("Skill source %s cache is empty; discovering", source.name)
                    await refresh()
            except Exception as exc:  # discovery failure must not hide a local hit
                logger.warning("Populating skill source %s failed: %s", source.name, exc)

    async def _search_sources(
        self, query: str, *, limit: int | None
    ) -> tuple[tuple[RankedStub, ...], tuple[str, ...]]:
        """Query every configured source, ranking what comes back (§7.6)."""
        cap = limit or self._max_candidates
        scored: list[tuple[SkillStub, float]] = []
        errors: list[str] = []
        for source in self._sources:
            try:
                stubs = await source.search(query, limit=cap)
            except Exception as exc:  # a dead source must not sink the search
                logger.warning("Skill source %s failed: %s", source.name, exc)
                errors.append(f"{source.name}: {exc}")
                continue
            # Source hit order is its own relevance signal: earlier means better.
            for rank, stub in enumerate(stubs):
                scored.append((stub, float(len(stubs) - rank)))
        ranked = rank_stubs(scored, limit=cap)
        return tuple(ranked), tuple(errors)

    # -- install ---------------------------------------------------------------

    def _sources_matching(self, source: str) -> list[SkillSource]:
        """Sources to search, tolerating the label a search result displayed.

        ``skill_search`` reports each hit's *origin kind* (``github``, ``catalog``,
        ``url``), but a source is addressed by its own ``name`` (``catalog``). A
        caller that echoes back what it was shown — which is exactly what the
        agent does — would otherwise match nothing and be told the skill does not
        exist, even though it is sitting in the cache. So an unmatched label
        filters nothing rather than silently excluding every source.
        """
        if not source:
            return list(self._sources)
        exact = [item for item in self._sources if item.name == source]
        if exact:
            return exact
        logger.debug("Source %r matched no source name; searching all sources", source)
        return list(self._sources)

    async def install(self, name: str, *, source: str = "") -> InstallAttempt:
        """Fetch and install one candidate through the broker (§7.4/§8.4).

        Searches the configured sources for ``name``, then hands the stub to the
        broker — which scans it and obeys the policy engine. A skill that needs
        approval comes back with an ``approval_id`` and stays in quarantine.
        """
        errors: list[str] = []
        match: tuple[SkillStub, SkillSource] | None = None
        candidates = self._sources_matching(source)
        for candidate_source in candidates:
            try:
                stubs = await candidate_source.search(name, limit=10)
            except Exception as exc:
                logger.warning("Skill source %s failed: %s", candidate_source.name, exc)
                errors.append(f"{candidate_source.name}: {exc}")
                continue
            found = _pick(stubs, name)
            if found is not None:
                match = (found, candidate_source)
                break

        if match is None:
            detail = f" (source errors: {'; '.join(errors)})" if errors else ""
            known = ", ".join(source.name for source in self._sources) or "none"
            return InstallAttempt(
                False,
                f"No skill named {name!r} in any source{detail}. "
                f"Searched: {known}. Run skill_search first to get an exact name.",
            )

        stub, origin = match
        if self._broker is None or self._skills_dir is None:
            # Say which half is missing: "the skill was found but this runtime
            # cannot install" is a different problem from "no such skill".
            missing = []
            if self._broker is None:
                missing.append("no install broker (skill store unavailable)")
            if self._skills_dir is None:
                missing.append("no skills directory")
            return InstallAttempt(
                False,
                f"Found {stub.name!r} but cannot install it: {'; '.join(missing)}",
                data={"name": stub.name, "origin": stub.origin},
            )

        report: InstallReport = await self._broker.install(
            stub, origin, skills_dir=self._skills_dir
        )
        if report.installed and self._on_install is not None:
            try:
                self._on_install()
            except Exception:  # a refresh failure must not hide a real install
                logger.warning("Post-install skill refresh failed", exc_info=True)
        return _from_report(report)


def _pick(stubs: list[SkillStub], name: str) -> SkillStub | None:
    """The stub that ``name`` addresses: an exact name, else the only hit."""
    for stub in stubs:
        if stub.name == name:
            return stub
    return stubs[0] if len(stubs) == 1 else None


def _from_report(report: Any) -> InstallAttempt:
    """Translate a broker report into a tool-facing attempt."""
    if report.installed:
        return InstallAttempt(
            True,
            f"Installed {report.name} -> {report.installed_path}",
            data={"name": report.name, "path": report.installed_path},
        )
    if report.pending_approval:
        return InstallAttempt(
            False,
            f"{report.name} needs user approval before it can be enabled",
            approval_id=report.outcome.approval_id,
            data={"name": report.name, "quarantined_path": report.quarantined_path},
        )
    return InstallAttempt(False, f"Rejected {report.name}: {report.outcome.reason}")

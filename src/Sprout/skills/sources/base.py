"""Skill sources: where a candidate skill can be found (design §7.3).

A source is a two-step contract: :meth:`SkillSource.search` returns cheap
:class:`SkillStub` records (no bodies), and :meth:`SkillSource.fetch` returns the
:class:`SkillBundle` for exactly one stub. Both are ``async`` (design §7.3) so a
source can ``await`` the policy-controlled execution layer — a local directory
does no I/O and simply returns, while the CLI/network sources await
:class:`~Sprout.execution.ProcessBroker` / :class:`~Sprout.execution.NetworkBroker`.
Nothing is installed by a source — that is the broker's job (design §7.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SkillStub:
    """A search hit: enough to decide whether to fetch the full bundle."""

    name: str
    source: str
    origin: str = ""
    description: str = ""
    version: str = ""
    tags: tuple[str, ...] = ()
    digest: str = ""
    trust: str = "untrusted"
    #: Branch, tag or commit to pin when fetching. Empty means the repository's
    #: default branch; a published manifest may name an exact ``ref`` so an
    #: install cannot silently drift to different content (§7.5).
    ref: str = ""
    #: How to install this skill itself when it is distributed rather than
    #: copied. Displayed to the user; never executed automatically (§7.5).
    install_command: str = ""
    #: External CLI binaries the skill needs on PATH.
    requires_cli: tuple[str, ...] = ()
    #: How to install those binaries. Display-only, like ``install_command``.
    cli_install_command: str = ""

    @property
    def cli_ready(self) -> bool:
        """True when every declared external CLI resolves on this machine."""
        import shutil

        return all(shutil.which(binary) for binary in self.requires_cli)


@dataclass(frozen=True, slots=True)
class SkillBundle:
    """The fetched content of a skill, staged but not yet installed."""

    stub: SkillStub
    files: Mapping[str, bytes] = field(default_factory=dict)
    script_text: str = ""

    @property
    def name(self) -> str:
        return self.stub.name


@runtime_checkable
class SkillSource(Protocol):
    """A place skills can be searched for and fetched from."""

    name: str

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]: ...

    async def fetch(self, stub: SkillStub) -> SkillBundle: ...

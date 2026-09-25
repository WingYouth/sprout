"""Versioned procedural knowledge (skills)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class SkillSource(StrEnum):
    """Where a skill came from (drives approval strength, design §8.4)."""

    LOCAL = "local"
    PROJECT = "project"
    EVOLVED = "evolved"
    CATALOG = "catalog"
    GITHUB = "github"
    URL = "url"


class TrustLevel(StrEnum):
    """How much a skill is trusted; gates injection visibility (design §4.4)."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"

    @property
    def injectable(self) -> bool:
        """Only ``trusted`` skills may enter the injected index."""
        return self is TrustLevel.TRUSTED


@dataclass(frozen=True, slots=True)
class Skill:
    """A versioned unit of procedural knowledge.

    The first five fields are the historical shape (kept in order for
    compatibility). Everything after ``enabled`` is added by the skills-system
    design (docs/SKILLS_SYSTEM_DESIGN.md §4.1) and defaults to a no-op value so
    existing callers keep working unchanged.
    """

    name: str
    version: str
    instructions: str
    required_tools: tuple[str, ...] = ()
    enabled: bool = True
    # -- index / provenance --
    description: str = ""
    tags: tuple[str, ...] = ()
    source: str = SkillSource.LOCAL.value
    origin: str = ""
    digest: str = ""
    # -- safety --
    trust: str = TrustLevel.UNTRUSTED.value
    # -- conditional activation (§6.3) --
    requires_toolsets: tuple[str, ...] = ()
    fallback_for_toolsets: tuple[str, ...] = ()
    pinned: bool = False
    # -- distribution & external CLI dependencies (§7.5) --
    #: How to install this skill itself, when it is distributed rather than
    #: copied (``npx skills add acme/pdf``). Displayed to the user; never run
    #: automatically — a remote string that gets executed is a shell injection.
    install_command: str = ""
    #: External CLI binaries the skill needs on PATH to work at all.
    requires_cli: tuple[str, ...] = ()
    #: How to install those binaries (``brew install pandoc``). Display-only.
    cli_install_command: str = ""
    #: Relative folder path used by the CLI skill menu and registry views.
    menu_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillRecord:
    """One entry of the local skill index (index.json + SQLite, design §4.2).

    Deliberately excludes ``instructions``: the injected index (L0) carries only
    a summary so it stays small.
    """

    name: str
    version: str
    description: str = ""
    tags: tuple[str, ...] = ()
    source: str = SkillSource.LOCAL.value
    origin: str = ""
    digest: str = ""
    trust: str = TrustLevel.UNTRUSTED.value
    enabled: bool = True
    pinned: bool = False
    path: str = ""
    updated_at: str = ""
    # -- distribution & external CLI dependencies (§7.5) --
    install_command: str = ""
    requires_cli: tuple[str, ...] = ()
    cli_install_command: str = ""
    #: The same hierarchy used by the CLI menu, persisted in the registry.
    menu_path: tuple[str, ...] = ()

    @classmethod
    def from_skill(
        cls,
        skill: Skill,
        *,
        path: str = "",
        updated_at: str = "",
        menu_path: tuple[str, ...] | None = None,
    ) -> SkillRecord:
        """Project a :class:`Skill` down to its index entry."""
        return cls(
            name=skill.name,
            version=skill.version,
            description=skill.description,
            tags=skill.tags,
            source=skill.source,
            origin=skill.origin,
            digest=skill.digest,
            trust=skill.trust,
            enabled=skill.enabled,
            pinned=skill.pinned,
            path=path,
            updated_at=updated_at,
            install_command=skill.install_command,
            requires_cli=skill.requires_cli,
            cli_install_command=skill.cli_install_command,
            menu_path=skill.menu_path if menu_path is None else tuple(menu_path),
        )

    def to_dict(self) -> dict[str, object]:
        """JSON-ready mapping (consumed by ``SkillIndex``, design §7.2)."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tags": list(self.tags),
            "source": self.source,
            "origin": self.origin,
            "digest": self.digest,
            "trust": self.trust,
            "enabled": self.enabled,
            "pinned": self.pinned,
            "path": self.path,
            "updated_at": self.updated_at,
            "install_command": self.install_command,
            "requires_cli": list(self.requires_cli),
            "cli_install_command": self.cli_install_command,
            "menu_path": list(self.menu_path),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SkillRecord:
        """Inverse of :meth:`to_dict` (tolerant of missing keys)."""
        raw_tags = data.get("tags") or ()
        raw_cli = data.get("requires_cli") or ()
        raw_menu = data.get("menu_path") or ()
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            description=str(data.get("description", "")),
            tags=tuple(str(tag) for tag in raw_tags),
            source=str(data.get("source", SkillSource.LOCAL.value)),
            origin=str(data.get("origin", "")),
            digest=str(data.get("digest", "")),
            trust=str(data.get("trust", TrustLevel.UNTRUSTED.value)),
            enabled=bool(data.get("enabled", True)),
            pinned=bool(data.get("pinned", False)),
            path=str(data.get("path", "")),
            updated_at=str(data.get("updated_at", "")),
            install_command=str(data.get("install_command", "")),
            requires_cli=tuple(str(item) for item in raw_cli),
            cli_install_command=str(data.get("cli_install_command", "")),
            menu_path=tuple(str(item) for item in raw_menu),
        )

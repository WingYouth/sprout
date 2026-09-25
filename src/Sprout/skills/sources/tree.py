"""A recursive scan of a local directory tree for skills (design §7.3).

:class:`~Sprout.skills.sources.local.LocalDirSource` answers "is there a skill
called X in this flat directory?" — it looks one level deep, because that is the
shape of ``~/.sprout/skills`` itself. That is the wrong question for a *foreign*
directory: a cloned skills repository, or a folder of hand-written skills, is
almost always nested (``skills/writing/docs/SKILL.md``), and a one-level scan
finds nothing there and reports it as "no skill named X" rather than "your path
is wrong".

This module answers the other question: *what skills are anywhere under this
path?* It walks the whole subtree and **prunes at the first skill root it
finds** — a directory holding a ``SKILL.md`` is one skill, so descending into it
would count its own ``assets/SKILL.md`` as a second, nameless skill.

Nothing here is installed and nothing here is trusted. The scan produces
:class:`FoundSkill` values; installing stays the broker's job (§7.4), so the
scanner's hard floor and the policy engine still see every one of them.
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from Sprout.skills.loader import load_skill_file, load_standard_skill
from Sprout.skills.models import Skill

logger = logging.getLogger("sprout.skills")

#: Directory names never descended into. ``node_modules``/``.git``/``.venv`` are
#: vendored noise; ``.fetched``/``.evolved``/``.quarantine``/``.hub`` are the
#: runtime's own bookkeeping inside a skills root — already-installed products
#: that an import must not pick up and re-offer as candidates.
PRUNE_DIRNAMES = frozenset(
    {
        "node_modules",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".hub",
        ".quarantine",
        ".fetched",
        ".evolved",
    }
)

#: Depth cap. Deep enough for any realistic ``repo/<group>/<skill>`` nesting,
#: shallow enough that pointing at a home directory cannot walk the world.
MAX_DEPTH = 8

#: How many candidates one scan may return. A misaimed path (``/`` or ``C:\\``)
#: would otherwise try to install thousands.
MAX_SKILLS = 500

SKILL_MANIFEST = "SKILL.md"


@dataclass(frozen=True, slots=True)
class FoundSkill:
    """One skill discovered on disk, with where it was found."""

    skill: Skill
    #: The ``SKILL.md`` file, or the ``.toml`` file, that defines the skill.
    artifact: Path
    #: The nearest ancestor directory the walk started from — reporting aid.
    root: Path

    @property
    def name(self) -> str:
        return self.skill.name


@dataclass(frozen=True, slots=True)
class ScanWarning:
    """A path that looked like a skill but could not be read."""

    path: Path
    reason: str


def scan_tree(
    root: str | Path,
    *,
    max_depth: int = MAX_DEPTH,
    max_skills: int = MAX_SKILLS,
    include_toml: bool = True,
    exclude: Sequence[str | Path] = (),
) -> tuple[list[FoundSkill], list[ScanWarning]]:
    """Every skill anywhere under ``root``, plus the paths that failed to parse.

    Returns ``(found, warnings)`` rather than raising: one malformed skill in a
    directory of twenty should not abort the other nineteen, but the user still
    needs to be told which one was skipped and why.

    ``exclude`` names subtrees to ignore. Importing a directory that contains
    the destination — ``sprout skills import . `` with the default
    ``~/.sprout/skills`` — would otherwise walk back into what it just wrote and
    rediscover every skill as a duplicate.
    """
    base = Path(root).resolve()
    found: list[FoundSkill] = []
    warnings: list[ScanWarning] = []
    if not base.is_dir():
        return found, warnings
    skip = {Path(item).resolve() for item in exclude}

    _walk(base, base, 0, max_depth, max_skills, include_toml, found, warnings, skip)
    found.sort(key=lambda item: item.name)
    return found, warnings


def _walk(
    directory: Path,
    base: Path,
    depth: int,
    max_depth: int,
    max_skills: int,
    include_toml: bool,
    found: list[FoundSkill],
    warnings: list[ScanWarning],
    skip: set[Path],
) -> None:
    """Depth-first walk that stops at the first skill root in each branch."""
    if depth > max_depth or len(found) >= max_skills:
        return

    manifest = directory / SKILL_MANIFEST
    if manifest.is_file():
        # A skill root: load it and stop. Descending would rediscover the
        # skill's own vendored files as separate skills. This applies at the
        # base too — pointing the import straight at one skill folder is the
        # single-skill case, not an empty scan.
        try:
            found.append(
                FoundSkill(skill=load_standard_skill(manifest), artifact=directory, root=base)
            )
        except (ValueError, OSError) as exc:
            warnings.append(ScanWarning(manifest, str(exc)))
        return

    if include_toml:
        for path in sorted(directory.glob("*.toml")):
            if len(found) >= max_skills:
                return
            try:
                skill = load_skill_file(path)
            except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
                warnings.append(ScanWarning(path, str(exc)))
                continue
            found.append(FoundSkill(skill=skill, artifact=path, root=base))

    try:
        entries = sorted(entry for entry in directory.iterdir() if entry.is_dir())
    except OSError:
        return
    for entry in entries:
        if entry.name in PRUNE_DIRNAMES or entry.name.startswith("."):
            continue
        if any(_is_within(entry, excluded) for excluded in skip):
            continue
        _walk(
            entry,
            base,
            depth + 1,
            max_depth,
            max_skills,
            include_toml,
            found,
            warnings,
            skip,
        )


def _is_within(path: Path, ancestor: Path) -> bool:
    """True when ``path`` is ``ancestor`` or lives underneath it."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == ancestor or ancestor in resolved.parents


__all__ = ["FoundSkill", "PRUNE_DIRNAMES", "ScanWarning", "scan_tree"]

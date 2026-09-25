"""Skill loading from (and serialization to) TOML files."""

from __future__ import annotations

import hashlib
import logging
import tomllib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from Sprout.skills.layout import EVOLVED_DIRNAME, FETCHED_DIRNAME
from Sprout.skills.models import Skill, SkillSource, TrustLevel

logger = logging.getLogger("sprout.skills")


def load_skill_file(path: Path) -> Skill:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    name = data.get("name")
    instructions = data.get("instructions")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Skill file {path} is missing a non-empty 'name'")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError(f"Skill file {path} is missing non-empty 'instructions'")
    required = data.get("required_tools", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(f"Skill file {path} has an invalid 'required_tools' list")
    version = data.get("version", "0.1.0")
    if not isinstance(version, str):
        raise ValueError(f"Skill file {path} has an invalid 'version'")
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"Skill file {path} has an invalid 'enabled' flag")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise ValueError(f"Skill file {path} has an invalid 'description'")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
        raise ValueError(f"Skill file {path} has an invalid 'tags' list")
    requires_cli = data.get("requires_cli", [])
    if not isinstance(requires_cli, list) or not all(
        isinstance(item, str) for item in requires_cli
    ):
        raise ValueError(f"Skill file {path} has an invalid 'requires_cli' list")
    return Skill(
        name=name.strip(),
        version=version,
        instructions=instructions,
        required_tools=tuple(required),
        enabled=enabled,
        description=description.strip(),
        tags=tuple(tags),
        source=SkillSource.LOCAL.value,
        trust=TrustLevel.TRUSTED.value,
        install_command=_text(data.get("install_command")),
        requires_cli=tuple(requires_cli),
        cli_install_command=_text(data.get("cli_install_command")),
    )


#: ``<root>/<subdir>`` → the ``source`` its skills are tagged with. Downloaded
#: and evolved skills live in hidden subdirectories of the skills root
#: (``layout.py``), so a top-level-only scan would install a skill and never
#: load it.
_MANAGED_SUBDIRS: dict[str, str] = {
    FETCHED_DIRNAME: "catalog",
    EVOLVED_DIRNAME: SkillSource.EVOLVED.value,
}


def iter_skill_artifacts(
    directory: str | Path, *, managed: bool = True
) -> list[tuple[Skill, Path]]:
    """Every loadable skill under ``directory``, paired with its artifact path.

    The artifact is the ``.toml`` file or the skill *directory*. ``managed``
    additionally descends into ``.fetched/`` / ``.evolved/`` and tags those
    skills with their real ``source``.

    **Managed skills are always loaded as ``untrusted``**, whatever they claim
    on disk: trust is a decision the registry makes (design §8.3), and a
    downloaded skill that could mark itself trusted by writing a frontmatter key
    would defeat the whole trust gate. ``.quarantine/`` is never scanned, so a
    staged skill stays invisible until it is promoted.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    # User-authored skills may be grouped in second-level folders such as
    # ``skills/code/python/SKILL.md``. Managed trees are scanned separately so
    # they retain their source and trust handling.
    found = _iter_flat(root, recursive=True)
    if not managed:
        return found
    for subdir, source in _MANAGED_SUBDIRS.items():
        found.extend(
            (
                replace(skill, source=source, trust=TrustLevel.UNTRUSTED.value),
                path,
            )
            for skill, path in _iter_flat(root / subdir, recursive=True)
        )
    return found


def skill_menu_path(artifact: str | Path, skills_dir: str | Path) -> tuple[str, ...]:
    """Return the registry/CLI hierarchy for an artifact below ``skills_dir``.

    A TOML skill uses its containing folders; a standard ``SKILL.md`` skill is
    represented by its skill directory. Hidden managed roots remain visible in
    the stored path so the database can distinguish fetched/evolved entries,
    while the CLI renders them as ordinary nested menu groups.
    """
    root = Path(skills_dir).expanduser().resolve()
    path = Path(artifact).expanduser().resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return ()
    if path.is_file():
        relative = relative.parent
    return tuple(relative.parts)


def _iter_flat(
    root: Path, *, recursive: bool = False
) -> list[tuple[Skill, Path]]:
    """Load Skill files directly or recursively below ``root``."""
    if not root.is_dir():
        return []
    found: list[tuple[Skill, Path]] = []
    paths = root.rglob("*.toml") if recursive else root.glob("*.toml")
    for path in sorted(paths):
        if _is_ignored_skill_path(root, path):
            continue
        try:
            skill = load_skill_file(path)
        except (ValueError, tomllib.TOMLDecodeError, OSError):
            logger.warning("Skipping invalid skill file: %s", path, exc_info=True)
            continue
        found.append((_with_artifact(skill, path), path))
    skill_paths = root.rglob("SKILL.md") if recursive else root.glob("*/SKILL.md")
    for skill_md in sorted(skill_paths):
        if _is_ignored_skill_path(root, skill_md):
            continue
        entry = skill_md.parent
        try:
            skill = load_standard_skill(skill_md)
        except (ValueError, OSError):
            logger.warning("Skipping invalid standard skill: %s", skill_md, exc_info=True)
            continue
        found.append((_with_artifact(skill, entry), entry))
    return found


def _is_ignored_skill_path(root: Path, path: Path) -> bool:
    """Keep managed and bookkeeping trees out of the ordinary scan."""
    relative = path.relative_to(root)
    ignored = {*_MANAGED_SUBDIRS, ".quarantine", ".hub"}
    return any(part in ignored for part in relative.parts)


def _with_artifact(skill: Skill, artifact: Path) -> Skill:
    """Record where a skill lives on disk and what its content hashes to."""
    return replace(skill, origin=str(artifact), digest=artifact_digest(artifact))


def load_skills(directory: str | Path) -> list[Skill]:
    """Load TOML skills and standard ``SKILL.md`` skill directories.

    Scans the skills root *and* the managed subdirectories (``.fetched/``,
    ``.evolved/``) so a skill installed by the broker is actually loadable; see
    :func:`iter_skill_artifacts` for the scan rules.
    """
    return [skill for skill, _ in iter_skill_artifacts(directory)]


def load_standard_skill(path: Path) -> Skill:
    """Load a standard skill directory's ``SKILL.md`` file."""
    text = path.read_text(encoding="utf-8")
    frontmatter: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            frontmatter = _parse_skill_frontmatter(text[4:end])
            body = text[end + 5 :]
    name = frontmatter.get("name") or path.parent.name
    instructions = body.strip()
    if not name or not instructions:
        raise ValueError(f"Invalid standard skill: {path}")
    required = _parse_required_tools(frontmatter.get("required_tools", ""))
    version = frontmatter.get("version", "0.1.0")
    enabled = frontmatter.get("enabled", "true").strip().casefold() != "false"
    return Skill(
        name=name,
        version=version,
        instructions=instructions,
        required_tools=tuple(required),
        enabled=enabled,
        description=frontmatter.get("description", "").strip(),
        tags=tuple(_parse_required_tools(frontmatter.get("tags", ""))),
        source=SkillSource.LOCAL.value,
        trust=TrustLevel.TRUSTED.value,
        install_command=frontmatter.get("install_command", "").strip(),
        requires_cli=tuple(_parse_required_tools(frontmatter.get("requires_cli", ""))),
        cli_install_command=frontmatter.get("cli_install_command", "").strip(),
    )


def _text(value: object) -> str:
    """Coerce an optional scalar setting to a stripped string."""
    return value.strip() if isinstance(value, str) else ""


def files_digest(files: Mapping[str, bytes]) -> str:
    """Content hash over ``{relative_path: bytes}``, stable across file order.

    This is the single digest scheme for the skills layer: the broker hashes a
    fetched bundle with it, the loader hashes an on-disk artifact with it, and
    the two must agree for a trust decision made at install time to still hold
    at load time (design §8.3). One implementation, so they cannot drift.
    """
    hasher = hashlib.sha256()
    for relative in sorted(files):
        hasher.update(relative.encode("utf-8"))
        hasher.update(files[relative])
    return "sha256:" + hasher.hexdigest()


def artifact_digest(artifact: str | Path) -> str:
    """Content hash of a skill artifact: a ``.toml`` file or a skill directory.

    Mirrors how the sources package the same artifact into a bundle (a single
    file keeps its own name as the relative path), so the digest computed here
    matches the one the broker recorded at install time.
    """
    path = Path(artifact)
    if path.is_file():
        return files_digest({path.name: path.read_bytes()})
    if path.is_dir():
        return files_digest(
            {
                file.relative_to(path).as_posix(): file.read_bytes()
                for file in sorted(path.rglob("*"))
                if file.is_file()
            }
        )
    return files_digest({})


def _parse_skill_frontmatter(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def _parse_required_tools(value: str) -> list[str]:
    value = value.strip().strip("[]")
    if not value:
        return []
    return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]


def skill_to_toml(skill: Skill) -> str:
    """Serialize a skill back to TOML (used by the evolution publisher)."""
    escaped_name = skill.name.replace('"', "'")
    escaped_version = skill.version.replace('"', "'")
    lines = [
        f'name = "{escaped_name}"',
        f'version = "{escaped_version}"',
        f"enabled = {'true' if skill.enabled else 'false'}",
    ]
    if skill.required_tools:
        tools = ", ".join(f'"{tool.replace(chr(34), chr(39))}"' for tool in skill.required_tools)
        lines.append(f"required_tools = [{tools}]")
    body = skill.instructions.replace('"""', "'''")
    lines.append(f'instructions = """\n{body}\n"""')
    return "\n".join(lines) + "\n"

"""A skill source backed by a local directory (design §7.3).

Used both for the user's own skill folders and, in tests, for a stand-in catalog.
Search is a cheap substring/tag match; nothing here is trusted — the broker still
scans and the policy engine still decides.
"""

from __future__ import annotations

import re
from pathlib import Path

from Sprout.skills.loader import artifact_digest, load_skill_file, load_standard_skill
from Sprout.skills.models import Skill
from Sprout.skills.sources.base import SkillBundle, SkillStub

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    {"a", "an", "the", "to", "for", "of", "and", "or", "in", "on", "with", "please", "help"}
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.casefold())
        if token not in _STOPWORDS and len(token) > 1
    }


class LocalDirSource:
    """Searches a directory of ``<name>.toml`` files and ``<name>/SKILL.md`` folders."""

    def __init__(self, root: str | Path, *, name: str = "local", source: str = "local") -> None:
        self.name = name
        self._root = Path(root)
        self._source = source

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        wanted = _tokens(query)
        hits: list[tuple[float, SkillStub]] = []
        for skill, artifact in self._iter_skills():
            haystack = _tokens(" ".join((skill.name, skill.description, *skill.tags)))
            overlap = wanted & haystack
            if not overlap:
                continue
            hits.append(
                (
                    float(len(overlap)),
                    SkillStub(
                        name=skill.name,
                        source=self._source,
                        origin=str(artifact),
                        description=skill.description,
                        version=skill.version,
                        tags=skill.tags,
                        digest=self._digest(artifact),
                        install_command=skill.install_command,
                        requires_cli=skill.requires_cli,
                        cli_install_command=skill.cli_install_command,
                    ),
                )
            )
        hits.sort(key=lambda item: (-item[0], item[1].name))
        return [stub for _, stub in hits[:limit]]

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        artifact = Path(stub.origin)
        if artifact.is_file():
            return SkillBundle(stub=stub, files={artifact.name: artifact.read_bytes()})
        files: dict[str, bytes] = {}
        if artifact.is_dir():
            for path in sorted(artifact.rglob("*")):
                if path.is_file():
                    files[path.relative_to(artifact).as_posix()] = path.read_bytes()
        return SkillBundle(stub=stub, files=files, script_text=self._script_text(files))

    # -- internals ---------------------------------------------------------

    def _iter_skills(self) -> list[tuple[Skill, Path]]:
        """Skills directly under the root, plus the root itself when it *is* one.

        The root case matters for ``--from``: pointing a source at
        ``.../skills/writing/docs`` — the skill directory itself — is the natural
        way to name one skill, and without it the search reports "no skill named
        X" for a directory that plainly is X.
        """
        if not self._root.is_dir():
            return []
        found: list[tuple[Skill, Path]] = []
        root_manifest = self._root / "SKILL.md"
        if root_manifest.is_file():
            try:
                found.append((load_standard_skill(root_manifest), self._root))
            except (ValueError, OSError):
                pass
        for path in sorted(self._root.glob("*.toml")):
            try:
                found.append((load_skill_file(path), path))
            except (ValueError, OSError):
                continue
        for entry in sorted(self._root.iterdir()):
            skill_md = entry / "SKILL.md"
            if entry.is_dir() and skill_md.is_file():
                try:
                    found.append((load_standard_skill(skill_md), entry))
                except (ValueError, OSError):
                    continue
        return found

    @staticmethod
    def _digest(artifact: Path) -> str:
        """Digest via the shared scheme so it matches install-time records."""
        return artifact_digest(artifact)

    @staticmethod
    def _script_text(files: dict[str, bytes]) -> str:
        """Concatenate script-like bodies so the shared hard floor can see them."""
        chunks: list[str] = []
        for relative, content in files.items():
            if Path(relative).suffix.lower() in {".sh", ".bash", ".py", ".ps1"}:
                try:
                    chunks.append(content.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
        return "\n".join(chunks)

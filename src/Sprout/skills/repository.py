"""Directory-backed skill persistence used by the evolution publisher."""

from __future__ import annotations

import logging
from pathlib import Path

from Sprout.skills.loader import load_skill_file, load_skills, skill_to_toml
from Sprout.skills.models import Skill

logger = logging.getLogger("sprout.skills")


class SkillRepository:
    """One ``<name>.toml`` file per skill under a root directory."""

    def __init__(self, directory: str | Path) -> None:
        self._root = Path(directory)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
        return self._root / f"{safe}.toml"

    def save(self, skill: Skill) -> Path:
        path = self._path_for(skill.name)
        path.write_text(skill_to_toml(skill), encoding="utf-8")
        return path

    def exists(self, name: str) -> bool:
        return self._path_for(name).exists()

    def load(self, name: str) -> Skill | None:
        path = self._path_for(name)
        if not path.exists():
            return None
        try:
            return load_skill_file(path)
        except ValueError:
            logger.warning("Failed to load skill %s from %s", name, path, exc_info=True)
            return None

    def load_all(self) -> list[Skill]:
        return load_skills(self._root)

    def delete(self, name: str) -> bool:
        path = self._path_for(name)
        if path.exists():
            path.unlink()
            return True
        return False

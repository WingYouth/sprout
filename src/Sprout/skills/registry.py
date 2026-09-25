"""Skill registry and its factory."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.registry.base import Registry
from Sprout.skills.loader import load_skills
from Sprout.skills.models import Skill, TrustLevel

if TYPE_CHECKING:
    from Sprout.skills.index import SkillIndex


class SkillRegistry:
    def __init__(self) -> None:
        self._registry: Registry[Skill] = Registry()

    def register(self, skill: Skill, *, replace: bool = True) -> None:
        self._registry.register(skill.name, skill, replace=replace)

    def reload(
        self,
        skills_dir: str | Path,
        *,
        index: SkillIndex | None = None,
    ) -> None:
        """Re-read ``skills_dir``, replacing what is registered.

        Called after a skill is installed so it becomes usable in the same
        session: the registry is a snapshot taken at assembly time, and a
        freshly promoted skill would otherwise stay invisible until restart.
        Trust is restored from ``index`` exactly as at startup (design §8.3).
        """
        fresh = create_skill_registry(skills_dir, index=index)
        self._registry = fresh._registry

    def unregister(self, name: str) -> None:
        self._registry.unregister(name)

    def get(self, name: str) -> Skill:
        return self._registry.get(name)

    def contains(self, name: str, *, enabled_only: bool = True) -> bool:
        return self._registry.contains(name, enabled_only=enabled_only)

    def list(self) -> dict[str, Skill]:
        return self._registry.list()

    def enable(self, name: str) -> None:
        self._registry.enable(name)

    def disable(self, name: str) -> None:
        self._registry.disable(name)


def create_skill_registry(
    skills_dir: str | Path | None = None,
    *,
    index: SkillIndex | None = None,
) -> SkillRegistry:
    """Load every skill under ``skills_dir`` into a registry.

    ``index`` is the ``index.json`` snapshot written from the skill store, i.e.
    the authority on what was installed and *approved* (design §8.3). When it is
    supplied, a skill whose recorded ``trust`` is ``trusted`` **and** whose
    content still hashes to the recorded digest is promoted to trusted here;
    everything else stays ``untrusted`` and is therefore kept out of the prompt.

    Passing no index keeps the historical behaviour for user-authored skills at
    the root (which load as trusted), while anything in ``.fetched/`` still fails
    closed — so a downloaded skill is never injected just because it is on disk.
    """
    registry = SkillRegistry()
    if skills_dir is None:
        return registry

    approved = _approved_by_name(index) if index is not None else {}
    for skill in load_skills(skills_dir):
        registry.register(_restore_trust(skill, approved.get(skill.name)))
    return registry


def _approved_by_name(index: SkillIndex) -> dict[str, tuple[str, str]]:
    """``name -> (trust, digest)`` for every entry the store knows about.

    A missing or unreadable snapshot yields an empty map, which fails closed:
    every downloaded skill then stays untrusted rather than defaulting to trusted.
    """
    try:
        return {record.name: (record.trust, record.digest) for record in index.load()}
    except Exception:  # a broken snapshot must never grant trust
        return {}


def _restore_trust(skill: Skill, approved: tuple[str, str] | None) -> Skill:
    """Promote a skill to trusted only if the store vouches for its exact content."""
    if approved is None:
        return skill
    trust, digest = approved
    if trust != TrustLevel.TRUSTED.value:
        return replace(skill, trust=TrustLevel.UNTRUSTED.value)
    if digest and digest != skill.digest:
        # Content changed since approval: the approval no longer applies (§8.4).
        return replace(skill, trust=TrustLevel.UNTRUSTED.value)
    return replace(skill, trust=TrustLevel.TRUSTED.value)

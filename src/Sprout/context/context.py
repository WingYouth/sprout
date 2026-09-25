"""AgentContext: the only window an agent has onto sessions, memory, and capabilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.context.workspace import WorkspaceContext
    from Sprout.memory.models import ContextMemory
    from Sprout.session.models import Session
    from Sprout.skills.models import Skill
    from Sprout.storage.contracts.knowledge import KnowledgeItem
    from Sprout.tools.base import Tool

#: Only ``trusted`` skills are ever injected (design §4.4). Kept as a literal so
#: this module stays free of a runtime dependency on the skills package.
_TRUSTED = "trusted"

#: How much of a skill body the prompt carries by default (design §6.1).
PROGRESSIVE = "progressive"
EAGER = "eager"


def _first_line(text: str, *, limit: int = 200) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


def _skill_visible(skill: Skill, tools: Mapping[str, Tool]) -> bool:
    """A skill is injectable when enabled, trusted, and its activation holds.

    ``requires_toolsets`` / ``fallback_for_toolsets`` hold tool names (Sprout has
    no separate toolset concept); a fallback stays hidden while its replacement
    tools are present.
    """
    if not skill.enabled or skill.trust != _TRUSTED:
        return False
    available = set(tools)
    if skill.requires_toolsets and not set(skill.requires_toolsets) <= available:
        return False
    if skill.fallback_for_toolsets and set(skill.fallback_for_toolsets) <= available:
        return False
    return True


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Everything an agent may read for one turn. No storage handles, no registries."""

    session: Session
    memory: ContextMemory | Sequence[Any] = ()
    knowledge: Sequence[KnowledgeItem] = ()
    tools: Mapping[str, Tool] = field(default_factory=dict)
    skills: Mapping[str, Skill] = field(default_factory=dict)
    user: Mapping[str, Any] = field(default_factory=dict)
    files: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    workspace: WorkspaceContext | None = None
    #: ``progressive`` injects the L0 index only; ``eager`` keeps the legacy body.
    skill_disclosure: str = PROGRESSIVE

    def visible_skills(self) -> tuple[Skill, ...]:
        """Skills eligible for injection this turn (trust + activation gated)."""
        return tuple(skill for skill in self.skills.values() if _skill_visible(skill, self.tools))

    def skills_index(self) -> str:
        """L0: one summary line per visible skill (design §6.1).

        Full bodies stay out of the prompt until the model asks for one.
        """
        lines: list[str] = []
        for skill in self.visible_skills():
            summary = skill.description.strip() or _first_line(skill.instructions)
            suffix = f" [tags: {', '.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"- {skill.name} (v{skill.version}){suffix}: {summary}")
        return "\n".join(lines)

    def skill_instructions(self) -> str:
        """Eager mode: concatenate enabled skill instructions for prompt assembly."""
        return "\n\n".join(
            f"# Skill: {skill.name} (v{skill.version})\n{skill.instructions}"
            for skill in self.skills.values()
            if skill.enabled
        )

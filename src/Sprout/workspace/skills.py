"""Skills ingestion for Workspace Intelligence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from Sprout.workspace.graph import WorkspaceEdge, WorkspaceNode
from Sprout.workspace.knowledge import ProjectKnowledgeItem
from Sprout.workspace.models import WorkspaceGranularity

_FRONTMATTER_RE = re.compile(r"(?ms)^---\n(.*?)\n---")


@dataclass(frozen=True, slots=True)
class SkillWorkspaceAnalysis:
    nodes: tuple[WorkspaceNode, ...] = ()
    edges: tuple[WorkspaceEdge, ...] = ()
    knowledge_items: tuple[ProjectKnowledgeItem, ...] = ()


class SkillWorkspaceAnalyzer:
    """Scan SKILL.md files into graph nodes and project knowledge items."""

    def analyze(self, workspace_id: str, skills_dir: str | Path) -> SkillWorkspaceAnalysis:
        root = Path(skills_dir).resolve()
        if not root.exists():
            return SkillWorkspaceAnalysis()

        nodes: list[WorkspaceNode] = []
        edges: list[WorkspaceEdge] = []
        knowledge_items: list[ProjectKnowledgeItem] = []
        for index, path in enumerate(sorted(root.rglob("SKILL.md"))):
            skill = self._read_skill(path)
            name = skill.get("name") or path.parent.name
            description = skill.get("description", "").strip()
            evidence = path.resolve().as_posix()

            skill_node = WorkspaceNode(
                id=f"{workspace_id}:skill:{name}",
                kind="skill",
                name=name,
                qualified_name=name,
                granularity=WorkspaceGranularity.SKILL.value,
            )
            nodes.append(skill_node)
            for tool in self._required_tools(skill):
                tool_node = WorkspaceNode(
                    id=f"{workspace_id}:tool:{tool}",
                    kind="tool",
                    name=tool,
                    qualified_name=tool,
                    granularity=WorkspaceGranularity.SKILL.value,
                )
                nodes.append(tool_node)
                edges.append(
                    WorkspaceEdge(
                        id=f"{skill_node.id}->{tool_node.id}:requires",
                        source=skill_node.id,
                        target=tool_node.id,
                        relation="requires",
                    )
                )
            knowledge_items.append(
                ProjectKnowledgeItem(
                    id=f"{workspace_id}:skill-knowledge:{index}",
                    statement=f"Skill: {name}"
                    + (f" - {description}" if description else ""),
                    kind="skill",
                    scope="skill",
                    evidence_ids=(evidence,),
                    confidence=1.0,
                )
            )

        return SkillWorkspaceAnalysis(
            nodes=tuple(nodes),
            edges=tuple(edges),
            knowledge_items=tuple(knowledge_items),
        )

    @staticmethod
    def _read_skill(path: Path) -> dict[str, str]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        match = _FRONTMATTER_RE.match(text)
        if not match:
            return {}

        result: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("\"'")
        return result

    @staticmethod
    def _required_tools(skill: dict[str, str]) -> tuple[str, ...]:
        raw = skill.get("required_tools", "")
        if not raw:
            return ()
        return tuple(
            item.strip()
            for item in raw.replace(",", "\n").splitlines()
            if item.strip()
        )


__all__ = ["SkillWorkspaceAnalysis", "SkillWorkspaceAnalyzer"]

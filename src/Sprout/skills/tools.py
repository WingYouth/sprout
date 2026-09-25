"""Agent-facing skill tools: the L1/L2 half of progressive disclosure (§6.1).

The L0 index is injected every turn (:meth:`AgentContext.skills_index`), and the
system message tells the model to call ``skill_view`` for the full instructions.
That tool has to exist, or the index is a dead end — which is exactly what this
module fixes.

Three tools, ordered by how much damage they can do:

* ``skill_view``   — read a skill body or a file inside it. Read-only.
* ``skill_search`` — match the local index; optionally crawl configured catalogs.
* ``skill_install``— hand a candidate to the broker. **High risk**: the broker
  scans it, the policy engine decides, and a human approves anything that came
  off the network (§8.4). Nothing here installs on its own.

Search results deliberately *display* ``install_command`` and never execute it: a
string fetched from the internet and then run is a shell injection, so the
command is shown to the human who approves the install, not run by the model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec

if TYPE_CHECKING:
    from Sprout.skills.models import Skill
    from Sprout.skills.resolver import SkillResolver

#: Cap on a single file returned by ``skill_view`` so one call cannot flood the
#: context window with a vendored data file.
MAX_VIEW_CHARS = 20_000


def _schema(properties: Mapping[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": required}


def _skills_by_name(skills: Mapping[str, Skill]) -> dict[str, Skill]:
    return {skill.name: skill for skill in skills.values()}


def _safe_relative(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` under ``root``, or ``None`` when it escapes."""
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


class SkillViewTool:
    """L1/L2: read a skill's full instructions, or one file inside it.

    ``skills`` may be a mapping or a zero-argument callable returning one. The
    callable form is what the runtime uses: a skill installed mid-session must
    become viewable without rebuilding the tool registry.
    """

    def __init__(self, skills: Mapping[str, Skill] | Callable[[], Mapping[str, Skill]]) -> None:
        self._provider: Callable[[], Mapping[str, Skill]] = (
            skills if callable(skills) else lambda: skills
        )
        self.spec = ToolSpec(
            name="skill_view",
            description=(
                "Read a skill's full instructions. Pass only 'name' for the skill "
                "body, or 'path' for one file inside the skill directory "
                "(references/, scripts/, templates/). Use this after seeing a "
                "skill listed in the available-skills index."
            ),
            input_schema=_schema(
                {
                    "name": {"type": "string", "description": "Skill name."},
                    "path": {
                        "type": "string",
                        "description": "Relative file path inside the skill directory.",
                        "default": "",
                    },
                },
                ["name"],
            ),
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult.failure("Argument 'name' must be a non-empty string")
        skills = _skills_by_name(self._provider())
        skill = skills.get(name.strip())
        if skill is None:
            known = ", ".join(sorted(skills)) or "none"
            return ToolResult.failure(f"Unknown skill {name!r}. Known skills: {known}")

        relative = arguments.get("path", "")
        if relative is None:
            relative = ""
        if not isinstance(relative, str):
            return ToolResult.failure("Argument 'path' must be a string")
        if not relative.strip():
            return ToolResult.success(
                f"# Skill: {skill.name} (v{skill.version})\n{skill.instructions}",
                data={"name": skill.name, "version": skill.version},
            )

        if not skill.origin:
            return ToolResult.failure(
                f"Skill {skill.name!r} has no files on disk (no origin recorded)"
            )
        root = Path(skill.origin)
        if root.is_file():
            # A single-file ``.toml`` skill has no directory to read from.
            return ToolResult.failure(
                f"Skill {skill.name!r} is a single file; only its body is available"
            )
        target = _safe_relative(root, relative)
        if target is None:
            return ToolResult.failure("Path escapes the skill directory")
        if not target.is_file():
            return ToolResult.failure(f"No such file in skill {skill.name!r}: {relative}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult.failure(f"Could not read {relative}: {exc}")
        clipped = text[:MAX_VIEW_CHARS]
        if len(text) > MAX_VIEW_CHARS:
            clipped += f"\n\n[truncated at {MAX_VIEW_CHARS} characters]"
        return ToolResult.success(
            clipped, data={"name": skill.name, "path": relative}
        )


class SkillSearchTool:
    """Find skills: local index first, configured catalogs only on request."""

    def __init__(self, resolver: SkillResolver) -> None:
        self._resolver = resolver
        self.spec = ToolSpec(
            name="skill_search",
            description=(
                "Search for skills that match a task. Checks installed skills "
                "first; set 'crawl' to also search configured remote catalogs. "
                "Remote hits are candidates only — nothing is installed, and any "
                "install_command shown must be confirmed with the user."
            ),
            input_schema=_schema(
                {
                    "query": {
                        "type": "string",
                        "description": "What the skill should do.",
                    },
                    "crawl": {
                        "type": "boolean",
                        "description": "Also search remote catalogs when nothing local matches.",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum candidates to return.",
                        "default": 5,
                    },
                },
                ["query"],
            ),
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.failure("Argument 'query' must be a non-empty string")
        crawl = bool(arguments.get("crawl", False))
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or limit < 1:
            limit = 5

        resolution = await self._resolver.resolve(query, crawl=crawl, limit=limit)
        return ToolResult.success(
            resolution.to_text(), data=resolution.to_dict()
        )


class SkillInstallTool:
    """Hand one candidate to the broker. Scans, decides, and asks a human."""

    def __init__(self, resolver: SkillResolver) -> None:
        self._resolver = resolver
        self.spec = ToolSpec(
            name="skill_install",
            description=(
                "Install a skill found by skill_search. The skill is downloaded, "
                "scanned for unsafe content, and checked against policy; anything "
                "from the network needs explicit user approval before it is "
                "enabled. Confirm the source and its install_command with the "
                "user before calling this."
            ),
            input_schema=_schema(
                {
                    "name": {
                        "type": "string",
                        "description": (
                            "Exact skill name as reported by skill_search. Copy it "
                            "verbatim — matching is case-sensitive."
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Optional. Only set this if you know which installer "
                            "source to use; leaving it empty searches all of them."
                        ),
                        "default": "",
                    },
                },
                ["name"],
            ),
            # Fetching third-party instructions into the runtime is exactly the
            # step the design doc gates behind approval (§8.4); the broker turns
            # this into an ApprovalManager request rather than installing.
            risk_level="high",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult.failure("Argument 'name' must be a non-empty string")
        source = arguments.get("source", "")
        if not isinstance(source, str):
            return ToolResult.failure("Argument 'source' must be a string")

        outcome = await self._resolver.install(name.strip(), source=source.strip())
        if outcome.ok:
            return ToolResult.success(outcome.message, data=outcome.data)
        if outcome.approval_id:
            return ToolResult.needs_approval(outcome.approval_id)
        return ToolResult.failure(outcome.message)

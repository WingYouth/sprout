"""MCP resources exposed to external clients."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.runtime.runtime import Runtime

RESOURCE_DEFINITIONS: list[dict[str, str]] = [
    {
        "uri": "sprout://info",
        "name": "sprout_info",
        "description": "Runtime self-description: agents, tools, skills, model providers, storage.",
    },
    {
        "uri": "sprout://skills",
        "name": "sprout_skills",
        "description": "All registered skills as JSON.",
    },
    {
        "uri": "sprout://tools",
        "name": "sprout_tools",
        "description": "All registered tool specs as JSON.",
    },
    {
        "uri": "sprout://workspaces",
        "name": "sprout_workspaces",
        "description": "All registered workspaces as JSON.",
    },
    {
        "uri": "sprout://tasks",
        "name": "sprout_tasks",
        "description": "All registered project tasks as JSON.",
    },
]


def register_resources(server: Any, runtime: Runtime) -> None:
    @server.resource(
        "sprout://info",
        name="sprout_info",
        description="Runtime self-description: agents, tools, skills, model providers, storage.",
    )
    async def sprout_info() -> str:
        return json.dumps(runtime.describe().as_dict(), indent=2, ensure_ascii=False)

    @server.resource(
        "sprout://skills",
        name="sprout_skills",
        description="All registered skills as JSON.",
    )
    async def sprout_skills() -> str:
        skills = runtime.list_skills()
        return json.dumps(
            [
                {
                    "name": skill.name,
                    "version": skill.version,
                    "instructions": skill.instructions,
                    "required_tools": list(skill.required_tools),
                }
                for skill in skills.values()
            ],
            indent=2,
            ensure_ascii=False,
        )

    @server.resource(
        "sprout://tools",
        name="sprout_tools",
        description="All registered tool specs as JSON.",
    )
    async def sprout_tools() -> str:
        specs = runtime.list_tool_specs()
        return json.dumps(
            [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "risk_level": spec.risk_level,
                }
                for spec in specs
            ],
            indent=2,
            ensure_ascii=False,
        )

    @server.resource(
        "sprout://workspaces",
        name="sprout_workspaces",
        description="All registered workspaces as JSON.",
    )
    async def sprout_workspaces() -> str:
        workspaces = await runtime.list_workspaces()
        return json.dumps(
            [
                {
                    "id": workspace.id,
                    "kind": workspace.kind.value,
                    "root": str(workspace.root),
                    "revision": workspace.revision,
                }
                for workspace in workspaces
            ],
            indent=2,
            ensure_ascii=False,
        )

    @server.resource(
        "sprout://tasks",
        name="sprout_tasks",
        description="All registered project tasks as JSON.",
    )
    async def sprout_tasks() -> str:
        tasks = await runtime.list_tasks()
        return json.dumps(
            [
                {
                    "id": task.id,
                    "workspace_id": task.workspace_id,
                    "instruction": task.instruction,
                    "status": task.status.value,
                    "source": task.source,
                }
                for task in tasks
            ],
            indent=2,
            ensure_ascii=False,
        )

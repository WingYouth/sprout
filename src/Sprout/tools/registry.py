"""Tool registry plus the built-in knowledge search tool."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.registry.base import Registry
from Sprout.tools.base import Tool
from Sprout.tools.project_analyze_tool import ProjectAnalyzeTool
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec
from Sprout.tools.system_tools import (
    CliDetectTool,
    CliDownloadTool,
    CliRunTool,
    GitInspectTool,
    GitWriteTool,
    GrepCheckTool,
    SkillScriptTool,
)

if TYPE_CHECKING:
    from Sprout.security.layer import SecurityLayer
    from Sprout.storage.bundle import StorageBundle
    from Sprout.storage.contracts.knowledge import KnowledgeStore


class ToolRegistry:
    def __init__(self) -> None:
        self._registry: Registry[Tool] = Registry()

    def register(self, tool: Tool, *, replace: bool = True) -> None:
        self._registry.register(tool.spec.name, tool, replace=replace)

    def unregister(self, name: str) -> None:
        self._registry.unregister(name)

    def get(self, name: str) -> Tool:
        return self._registry.get(name)

    def contains(self, name: str) -> bool:
        return self._registry.contains(name)

    def list(self) -> dict[str, Tool]:
        return self._registry.list()

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._registry.list().values()]


class KnowledgeSearchTool:
    """Low-risk built-in tool that lets agents search the knowledge store."""

    def __init__(self, knowledge: KnowledgeStore, *, default_limit: int = 5) -> None:
        self._knowledge = knowledge
        self._default_limit = default_limit
        self.spec = ToolSpec(
            name="knowledge_search",
            description="Search the local knowledge base for relevant knowledge, "
            "FAQs, and procedures.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": default_limit,
                    },
                },
                "required": ["query"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.failure("Argument 'query' must be a non-empty string")
        limit = arguments.get("limit", self._default_limit)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = self._default_limit
        items = await self._knowledge.search(query, limit=max(1, limit))
        if not items:
            return ToolResult.success("No knowledge matched the query.")
        blocks = [
            f"[{item.id}] ({getattr(item, 'kind', 'knowledge')}) {item.content}"
            for item in items
        ]
        payload = [
            {"id": item.id, "kind": getattr(item, "kind", "knowledge"), "content": item.content}
            for item in items
        ]
        return ToolResult.success("\n\n".join(blocks), data=payload)


class RequestWorkspaceTool:
    """Ask the runtime for a workspace when the agent needs one to proceed.

    The conversation-path agent has no write tools — those live on AGENT nodes,
    which only exist once a task has been compiled, and a task needs a
    workspace. So an agent that correctly recognises "write me X" has no way to
    act on it and no way to say so through a channel the runtime listens on: it
    either refuses in prose or invents its own way of asking (asking for an
    absolute path, say), neither of which the runtime can turn into a task.

    This tool is that channel. It performs **no** side effect — it takes no
    arguments and registers nothing. Invoking it raises a flag that the agent
    loop propagates to the runtime, which holds the turn and asks the operator
    for a directory through the same consent path a keyword-detected task uses.
    That is why it is low risk and needs no approval: the decision point stays
    at the runtime, where consent is actually gathered.

    Deliberately *not* keyword-driven. The runtime's text-level gate can only
    guess from the wording, and a typo ("写一一个") or an unusual phrasing
    defeats it entirely. The agent knows what the user meant from the whole
    turn, so putting the request here is what makes intent detection reliable
    rather than best-effort.
    """

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="request_workspace",
            description=(
                "Call this only when the user gives a concrete instruction to "
                "create, modify, or write a specific file, and no workspace is "
                "bound to this session. Do NOT call it for questions about your "
                "abilities, such as 'can you write code?' — answer those "
                "directly. Creating and editing files requires a workspace; "
                "without one you have no write tools. Call it instead of "
                "explaining that you cannot, and instead of asking the user for "
                "a path. Do not guess a path and do not ask for an absolute "
                "path: this tool lets the runtime ask the user for the "
                "directory, which is the only way a workspace can be granted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "One sentence on what the user asked for, so the "
                            "request is understandable if it is read later."
                        ),
                    }
                },
                "required": [],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        reason = str(arguments.get("reason") or "").strip()
        return ToolResult.needs_workspace(
            "A workspace is required to write files. This request has been "
            "passed to the runtime, which will ask the operator which "
            "directory to use and then carry out the original instruction. "
            "Tell the user that briefly and stop — do not ask them for a path "
            "yourself and do not attempt the work another way."
            + (f" (for: {reason})" if reason else "")
        )


def create_tool_registry(
    storage: StorageBundle | None = None,
    *,
    security: SecurityLayer | None = None,
    workspace_root: str | Path | None = None,
    skills_dir: str | Path | None = None,
) -> ToolRegistry:
    """Create the tool registry, registering built-ins that need no configuration.

    When a security layer is supplied the CLI tools take its SSRF guard and its
    secret broker, so the agent tool path enforces the same network policy and
    the same child-process environment policy as the brokers it bypasses.
    """
    registry = ToolRegistry()
    if storage is not None and storage.knowledge is not None:
        registry.register(KnowledgeSearchTool(storage.knowledge))
    # Available on the conversation path, where the agent has no write tools:
    # it is how such an agent reports "this needs a workspace" to the runtime
    # instead of refusing in prose.
    registry.register(RequestWorkspaceTool())
    registry.register(GrepCheckTool())
    registry.register(ProjectAnalyzeTool())
    registry.register(CliDetectTool())
    registry.register(
        CliDownloadTool(guard=security.guard if security is not None else None)
    )
    registry.register(
        CliRunTool(
            secrets=security.secrets if security is not None else None,
            allowed_roots=(workspace_root,) if workspace_root is not None else None,
        )
    )
    registry.register(GitInspectTool())
    registry.register(GitWriteTool())
    if skills_dir is not None:
        registry.register(SkillScriptTool(skills_dir))
    return registry

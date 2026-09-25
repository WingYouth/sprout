"""MCP tools exposed to external clients.

Only read/search operations and the message flow are exposed here; risky
operations (storage writes, approval decisions, evolution publishing) are
deliberately NOT exposed over MCP. An external agent may raise an approval
request, but granting it stays with a human operator (SEMA spec 11.5).
Each tool calls a Runtime public service, never storage directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.message.models import Message
    from Sprout.runtime.runtime import Runtime

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "sprout_message",
        "description": "Send a message through the SEAM Sprout runtime and return its reply.",
        "arguments": {"message": "str", "session_id": "str | None"},
    },
    {
        "name": "sprout_session_create",
        "description": "Create a new conversation session and return its id.",
        "arguments": {"user_id": "str = 'mcp-client'"},
    },
    {
        "name": "sprout_session_history",
        "description": "Return the stored turns of a session, oldest first.",
        "arguments": {"session_id": "str", "limit": "int = 20"},
    },
    {
        "name": "sprout_skill_list",
        "description": "List enabled skills with name, version, and required tools.",
        "arguments": {},
    },
    {
        "name": "sprout_knowledge_search",
        "description": "Search the local knowledge store (knowledge, FAQs, procedures).",
        "arguments": {"query": "str", "limit": "int = 5"},
    },
    {
        "name": "workspace_scan",
        "description": "Open and scan a local or Git workspace.",
        "arguments": {"path": "str"},
    },
    {
        "name": "task_create",
        "description": "Create a project task in a workspace.",
        "arguments": {"workspace_id": "str", "instruction": "str"},
    },
    {
        "name": "task_execute",
        "description": "Execute a project task through the runtime.",
        "arguments": {"task_id": "str"},
    },
    {
        "name": "task_changes",
        "description": "List change proposals for a task.",
        "arguments": {"task_id": "str"},
    },
    {
        "name": "workspace_query",
        "description": "Return workspace metadata and manifest.",
        "arguments": {"workspace_id": "str"},
    },
    {
        "name": "task_plan",
        "description": "Generate a ReadPlan for a task.",
        "arguments": {"task_id": "str"},
    },
    {
        "name": "sandbox_diff",
        "description": "Return sandbox diffs from change proposals for a task.",
        "arguments": {"task_id": "str"},
    },
    {
        "name": "trajectory_query",
        "description": "Return recorded trajectory events for a task.",
        "arguments": {"task_id": "str"},
    },
    {
        "name": "sandbox_test",
        "description": "Run a known test command for a task in its workspace.",
        "arguments": {"task_id": "str", "command": "list[str]"},
    },
    {
        "name": "proposal_show",
        "description": "Show a change proposal and its diffs.",
        "arguments": {"proposal_id": "str"},
    },
    {
        "name": "proposal_request_approval",
        "description": (
            "Mark a change proposal as pending human approval. "
            "Approval itself is granted by a human outside MCP."
        ),
        "arguments": {"proposal_id": "str"},
    },
    {
        "name": "proposal_reject",
        "description": "Reject a pending change proposal.",
        "arguments": {"proposal_id": "str", "reason": "str = ''"},
    },
    {
        "name": "proposal_apply",
        "description": "Apply an approved change proposal.",
        "arguments": {"proposal_id": "str"},
    },
]


def register_tools(server: Any, runtime: Runtime) -> None:
    from Sprout.message.models import Message

    @server.tool(
        name="sprout_message",
        description="Send a message through the SEAM Sprout runtime and return its reply.",
    )
    async def sprout_message(message: str, session_id: str | None = None) -> str:
        msg: Message = Message(
            content=message,
            channel="mcp",
            user_id="mcp-client",
            session_id=session_id,
        )
        reply = await runtime.handle(msg)
        return reply.content

    @server.tool(
        name="sprout_session_create",
        description="Create a new conversation session and return its id.",
    )
    async def sprout_session_create(user_id: str = "mcp-client") -> str:
        session = await runtime.create_session(user_id)
        return session.id

    @server.tool(
        name="sprout_session_history",
        description="Return the stored turns of a session, oldest first.",
    )
    async def sprout_session_history(session_id: str, limit: int = 20) -> str:
        turns = await runtime.history(session_id, limit=limit)
        if not turns:
            return f"No history for session {session_id}."
        lines = [f"{turn.role}: {turn.content}" for turn in turns]
        return "\n".join(lines)

    @server.tool(
        name="sprout_skill_list",
        description="List enabled skills with name, version, and required tools.",
    )
    async def sprout_skill_list() -> str:
        skills = runtime.list_skills()
        if not skills:
            return "No skills registered."
        return json.dumps(
            [
                {
                    "name": skill.name,
                    "version": skill.version,
                    "required_tools": list(skill.required_tools),
                    "enabled": skill.enabled,
                }
                for skill in skills.values()
            ],
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="sprout_knowledge_search",
        description="Search the local knowledge store (knowledge, FAQs, procedures).",
    )
    async def sprout_knowledge_search(query: str, limit: int = 5) -> str:
        items = await runtime.search_knowledge(query, limit=limit)
        if not items:
            return "No knowledge matched the query."
        blocks = [f"[{item.id}] ({item.kind}) {item.content}" for item in items]
        return "\n\n".join(blocks)

    @server.tool(
        name="workspace_scan",
        description="Open and scan a local or Git workspace.",
    )
    async def workspace_scan(path: str) -> str:
        workspace = await runtime.open_workspace(path)
        manifest = await runtime.scan_workspace(workspace.id)
        return json.dumps(
            {
                "workspace_id": workspace.id,
                "kind": workspace.kind.value,
                "root": str(workspace.root),
                "detected_languages": list(manifest.detected_languages),
                "test_commands": list(manifest.test_commands),
                "build_commands": list(manifest.build_commands),
            },
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="task_create",
        description="Create a project task in a workspace.",
    )
    async def task_create(workspace_id: str, instruction: str) -> str:
        task = await runtime.create_task(workspace_id, instruction)
        return task.id

    @server.tool(
        name="task_execute",
        description="Execute a project task through the runtime.",
    )
    async def task_execute(task_id: str) -> str:
        task = await runtime.get_task(task_id)
        if task is None:
            return f"Task not found: {task_id}"
        result = await runtime.execute(task)
        return json.dumps(
            {
                "task_id": result.task_id,
                "status": result.status.value,
                "error": result.error,
            },
            indent=2,
        )

    @server.tool(
        name="task_changes",
        description="List change proposals for a task.",
    )
    async def task_changes(task_id: str) -> str:
        proposals = await runtime.list_change_proposals(task_id)
        if not proposals:
            return "No change proposals."
        return json.dumps(
            [
                {
                    "id": proposal.id,
                    "status": proposal.status.value,
                    "risk": proposal.risk,
                    "files_changed": list(proposal.files_changed),
                }
                for proposal in proposals
            ],
            indent=2,
        )

    @server.tool(
        name="workspace_query",
        description="Return workspace metadata and manifest.",
    )
    async def workspace_query(workspace_id: str) -> str:
        workspace = await runtime.get_workspace(workspace_id)
        if workspace is None:
            return f"Workspace not found: {workspace_id}"
        manifest = workspace.manifest
        return json.dumps(
            {
                "workspace_id": workspace.id,
                "kind": workspace.kind.value,
                "root": str(workspace.root),
                "detected_languages": list(manifest.detected_languages) if manifest else [],
                "test_commands": list(manifest.test_commands) if manifest else [],
                "build_commands": list(manifest.build_commands) if manifest else [],
            },
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="task_plan",
        description="Generate a ReadPlan for a task.",
    )
    async def task_plan(task_id: str) -> str:
        plan = await runtime.plan_task(task_id)
        return json.dumps(
            {
                "task_id": plan.task_id,
                "purpose": plan.purpose,
                "resources": [ref.path for ref in plan.resources],
                "excludes": list(plan.excludes),
            },
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="sandbox_diff",
        description="Return sandbox diffs from change proposals for a task.",
    )
    async def sandbox_diff(task_id: str) -> str:
        proposals = await runtime.list_change_proposals(task_id)
        if not proposals:
            return "No change proposals."
        diffs = [
            {
                "proposal_id": proposal.id,
                "diff": diff.diff_text,
            }
            for proposal in proposals
            for diff in proposal.diffs
        ]
        return json.dumps(diffs, indent=2, ensure_ascii=False)

    @server.tool(
        name="trajectory_query",
        description="Return recorded trajectory events for a task.",
    )
    async def trajectory_query(task_id: str) -> str:
        events = await runtime.read_trajectory(task_id)
        if not events:
            return f"No trajectory for task {task_id}."
        return json.dumps(
            [
                {
                    "id": event.id,
                    "name": event.name,
                    "task_id": event.task_id,
                    "payload": dict(event.payload),
                }
                for event in events
            ],
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="sandbox_test",
        description="Run a known test command for a task in its workspace.",
    )
    async def sandbox_test(task_id: str, command: list[str]) -> str:
        result = await runtime.run_task_process(task_id, tuple(command))
        return json.dumps(
            {
                "command": list(result.command),
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "allowed": result.allowed,
                "error": result.error,
            },
            indent=2,
        )

    @server.tool(
        name="proposal_show",
        description="Show a change proposal and its diffs.",
    )
    async def proposal_show(proposal_id: str) -> str:
        proposal = await runtime.find_change_proposal(proposal_id)
        if proposal is None:
            return f"Proposal not found: {proposal_id}"
        return json.dumps(
            {
                "id": proposal.id,
                "task_id": proposal.task_id,
                "status": proposal.status.value,
                "risk": proposal.risk,
                "files_changed": list(proposal.files_changed),
                "diffs": [diff.diff_text for diff in proposal.diffs],
            },
            indent=2,
            ensure_ascii=False,
        )

    @server.tool(
        name="proposal_request_approval",
        description=(
            "Mark a change proposal as pending human approval. "
            "Approval itself is granted by a human outside MCP."
        ),
    )
    async def proposal_request_approval(proposal_id: str) -> str:
        proposal = await runtime.find_change_proposal(proposal_id)
        if proposal is None:
            return f"Proposal not found: {proposal_id}"
        # External agents may raise the request, never decide it (spec 11.5).
        updated = await runtime.request_change_approval(proposal.id)
        return updated.status.value

    @server.tool(
        name="proposal_reject",
        description="Reject a pending change proposal.",
    )
    async def proposal_reject(proposal_id: str, reason: str = "") -> str:
        proposal = await runtime.find_change_proposal(proposal_id)
        if proposal is None:
            return f"Proposal not found: {proposal_id}"
        updated = await runtime.reject_change_proposal(proposal.id, reason=reason)
        return updated.status.value

    @server.tool(
        name="proposal_apply",
        description="Apply an approved change proposal.",
    )
    async def proposal_apply(proposal_id: str) -> str:
        proposal = await runtime.find_change_proposal(proposal_id)
        if proposal is None:
            return f"Proposal not found: {proposal_id}"
        result = await runtime.apply_change_proposal(proposal.id)
        return json.dumps(
            {
                "proposal_id": result.proposal_id,
                "applied": result.applied,
                "reason": result.reason,
            },
            indent=2,
        )

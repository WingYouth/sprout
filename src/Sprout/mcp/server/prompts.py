"""MCP prompts exposed to external clients."""

from __future__ import annotations

from typing import Any

PROMPT_DEFINITIONS: list[dict[str, str]] = [
    {
        "name": "sprout_chat",
        "description": "Wrap a user message as a prompt for the Sprout runtime.",
        "arguments": "message: str",
    },
    {
        "name": "sprout_skill_review",
        "description": "Produce a review checklist prompt for one skill.",
        "arguments": "skill_name: str",
    },
    {
        "name": "workspace_scan_prompt",
        "description": "Prompt another agent to scan a workspace with SEMA.",
        "arguments": "path: str",
    },
    {
        "name": "task_execute_prompt",
        "description": "Prompt another agent to execute a SEMA task.",
        "arguments": "task_id: str",
    },
    {
        "name": "approval_review_prompt",
        "description": "Prompt another agent to review a change proposal.",
        "arguments": "proposal_id: str",
    },
]


def register_prompts(server: Any) -> None:
    @server.prompt(
        name="sprout_chat",
        description="Wrap a user message as a prompt for the Sprout runtime.",
    )
    def sprout_chat(message: str) -> str:
        return (
            "You are Sprout, an embedded agent runtime. "
            f"Respond helpfully to the following user message:\n\n{message}"
        )

    @server.prompt(
        name="sprout_skill_review",
        description="Produce a review checklist prompt for one skill.",
    )
    def sprout_skill_review(skill_name: str) -> str:
        return (
            "Review the skill "
            f"'{skill_name}':\n"
            "1. Are the instructions unambiguous?\n"
            "2. Are the required tools available and low-risk?\n"
            "3. Does the version follow semantic versioning?\n"
            "4. Should this skill be enabled by default?\n"
        )

    @server.prompt(
        name="workspace_scan_prompt",
        description="Prompt another agent to scan a workspace with SEMA.",
    )
    def workspace_scan_prompt(path: str) -> str:
        return (
            f"Scan the workspace at '{path}' using the workspace_scan MCP tool. "
            "Report detected languages, test commands, and build commands."
        )

    @server.prompt(
        name="task_execute_prompt",
        description="Prompt another agent to execute a SEMA task.",
    )
    def task_execute_prompt(task_id: str) -> str:
        return (
            f"Execute SEMA task '{task_id}' using task_execute. "
            "Then inspect task_changes and trajectory_query before reporting."
        )

    @server.prompt(
        name="approval_review_prompt",
        description="Prompt another agent to review a change proposal.",
    )
    def approval_review_prompt(proposal_id: str) -> str:
        return (
            f"Review change proposal '{proposal_id}' using proposal_show. "
            "Check risk, changed files, and diff. Then call "
            "proposal_request_approval or proposal_reject; the approval itself "
            "is granted by a human operator outside MCP."
        )

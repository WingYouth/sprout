"""Normalized tool execution result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    content: str = ""
    data: Any = None
    error: str | None = None
    approval_id: str | None = None
    #: Set by ``request_workspace``: the agent recognised a coding request it
    #: cannot carry out, and is asking the **runtime** to obtain a workspace
    #: rather than improvising a way to ask the user itself. The runtime is the
    #: only layer that can hold the turn and resume it, so the tool reports the
    #: need instead of acting on it.
    workspace_request: bool = False

    @classmethod
    def success(cls, content: str = "", data: Any = None) -> ToolResult:
        return cls(ok=True, content=content, data=data)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)

    @classmethod
    def denied(cls, reason: str) -> ToolResult:
        return cls(ok=False, error=reason)

    @classmethod
    def needs_approval(cls, approval_id: str) -> ToolResult:
        return cls(ok=False, approval_id=approval_id)

    @classmethod
    def needs_workspace(cls, reason: str) -> ToolResult:
        return cls(ok=True, content=reason, workspace_request=True)

    def to_text(self) -> str:
        """Render the result for consumption by the model."""
        if self.ok:
            return self.content
        if self.approval_id:
            return (
                "This tool call requires human approval before it can run "
                f"(approval id: {self.approval_id}). Ask the user to approve it."
            )
        return f"Tool error: {self.error}"

"""Tool protocol implemented by every tool source (Python, HTTP, MCP)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec


class Tool(Protocol):
    spec: ToolSpec

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult: ...

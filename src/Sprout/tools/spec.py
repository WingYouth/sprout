"""Uniform tool specification. Python, HTTP, and MCP tools all use this."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Tool identity plus a JSON-Schema description of its arguments."""

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    risk_level: str = "low"

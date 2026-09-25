"""Unified capability model.

Tools, skills, workflows, MCP, agents, analyzers, and learned capabilities
all share this identity contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CapabilityKind(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    WORKFLOW = "workflow"
    MCP = "mcp"
    AGENT = "agent"
    ANALYZER = "analyzer"
    PROCESS = "process"
    LEARNED = "learned"


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    version: str
    kind: CapabilityKind
    required_permissions: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    capability_id: str
    version: str
    target: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

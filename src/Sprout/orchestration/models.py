"""Task orchestration domain models.

The orchestrator owns the execution graph. Agents and tools are executors
inside graph nodes, not top-level controllers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class NodeType(StrEnum):
    READ = "read"
    ANALYZE = "analyze"
    PLAN = "plan"
    AGENT = "agent"
    TOOL = "tool"
    MCP = "mcp"
    PROCESS = "process"
    SANDBOX = "sandbox"
    SUBTASK = "subtask"
    APPROVAL = "approval"
    EVALUATION = "evaluation"
    APPLY = "apply"


class NodeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class DataRef:
    id: str
    store: str = "blob"
    key: str = ""
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class NodeBudget:
    max_attempts: int = 1
    timeout_seconds: float = 0.0
    max_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionNode:
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    type: NodeType = NodeType.TOOL
    dependencies: tuple[str, ...] = ()
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    budget: NodeBudget = field(default_factory=NodeBudget)
    result_ref: DataRef | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    task_id: str
    nodes: tuple[ExecutionNode, ...] = ()
    entry_node_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

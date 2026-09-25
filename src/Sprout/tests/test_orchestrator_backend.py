"""Tests for the local orchestrator backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from Sprout.orchestration.models import ExecutionGraph, ExecutionNode, NodeBudget, NodeType
from Sprout.orchestration.terminal.local import LocalOrchestratorBackend
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.metadata import SqliteMetadataStore
from Sprout.task.models import TaskStatus


def test_local_orchestrator_backend_executes_graph(tmp_path: Path) -> None:
    store = SqliteMetadataStore(SqliteDatabase(tmp_path / "metadata.db"))
    node = ExecutionNode(task_id="task-1", type=NodeType.TOOL)
    graph = ExecutionGraph(task_id="task-1", nodes=(node,), entry_node_ids=(node.id,))

    async def run() -> None:
        result = await LocalOrchestratorBackend(store).execute(graph)
        assert result.status is TaskStatus.COMPLETED

    asyncio.run(run())


def test_local_orchestrator_enforces_node_timeout(tmp_path: Path) -> None:
    store = SqliteMetadataStore(SqliteDatabase(tmp_path / "metadata.db"))
    node = ExecutionNode(
        task_id="task-1",
        type=NodeType.TOOL,
        budget=NodeBudget(timeout_seconds=0.05),
    )
    graph = ExecutionGraph(task_id="task-1", nodes=(node,), entry_node_ids=(node.id,))

    async def slow_handler(_node: ExecutionNode) -> None:
        await asyncio.sleep(1)

    async def run() -> None:
        result = await LocalOrchestratorBackend(store).execute(
            graph, handler=slow_handler
        )
        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert "TimeoutError" in result.error

    asyncio.run(run())


def test_orchestrator_skips_verify_loops_after_a_green_evaluation(
    tmp_path: Path,
) -> None:
    store = SqliteMetadataStore(SqliteDatabase(tmp_path / "metadata.db"))
    eval_one = ExecutionNode(
        id="task-1:evaluation",
        task_id="task-1",
        type=NodeType.EVALUATION,
    )
    agent_two = ExecutionNode(
        id="task-1:agent:1",
        task_id="task-1",
        type=NodeType.AGENT,
        dependencies=(eval_one.id,),
    )
    eval_two = ExecutionNode(
        id="task-1:evaluation:1",
        task_id="task-1",
        type=NodeType.EVALUATION,
        dependencies=(agent_two.id,),
    )
    approval = ExecutionNode(
        id="task-1:approval",
        task_id="task-1",
        type=NodeType.APPROVAL,
        dependencies=(eval_two.id,),
    )
    apply = ExecutionNode(
        id="task-1:apply",
        task_id="task-1",
        type=NodeType.APPLY,
        dependencies=(approval.id,),
    )
    graph = ExecutionGraph(
        task_id="task-1",
        nodes=(eval_one, agent_two, eval_two, approval, apply),
        entry_node_ids=(eval_one.id,),
    )
    called: list[str] = []

    async def handler(node: ExecutionNode) -> dict:
        called.append(node.id)
        if node.type is NodeType.EVALUATION:
            return {"status": "passed"}
        return {}

    async def run() -> None:
        result = await LocalOrchestratorBackend(store).execute(
            graph, handler=handler
        )
        assert result.status is TaskStatus.COMPLETED
        assert called == [
            "task-1:evaluation",
            "task-1:approval",
            "task-1:apply",
        ]

    asyncio.run(run())

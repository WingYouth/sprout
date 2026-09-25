"""Sequential execution graph runner with resume, retry, and budgets.

The runner owns node scheduling. It restores node status from the metadata
store first, so re-running a task resumes it instead of repeating finished
work (SEMA spec 19.2). Approval nodes park the graph in WAITING_APPROVAL
until a human decides (spec 8.3, 11.5).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from Sprout.orchestration.models import (
    ExecutionGraph,
    ExecutionNode,
    NodeStatus,
    NodeType,
)
from Sprout.runtime.state import NodeStateMachine, TaskStateMachine
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.task.models import TaskBudget, TaskResult, TaskStatus
from Sprout.trajectory.models import TrajectoryEvent

NodeHandler = Callable[[ExecutionNode], Awaitable[Any] | Any] | None


@dataclass(frozen=True, slots=True)
class NodeResult:
    node_id: str
    status: NodeStatus
    output: Any = None
    error: str | None = None


class SequentialOrchestrator:
    """Runs graph nodes in declaration order.

    Sequential execution keeps the first implementation deterministic and
    auditable; the graph model already carries dependencies for a future
    parallel scheduler.
    """

    def __init__(self, metadata: MetadataStore) -> None:
        self._metadata = metadata

    async def execute(
        self,
        graph: ExecutionGraph,
        *,
        handler: NodeHandler = None,
        recorder: Any | None = None,
        budget: TaskBudget | None = None,
    ) -> TaskResult:
        nodes = await self._restore(graph)
        deadline = None
        if budget is not None and budget.max_duration_seconds > 0:
            deadline = time.monotonic() + budget.max_duration_seconds

        await self._update_task_status(
            graph.task_id, TaskStatus.RUNNING, recorder
        )
        await self._record(recorder, "task.started", graph.task_id)

        statuses = {node.id: node.status for node in nodes}
        nodes = list(nodes)
        index = 0
        while index < len(nodes):
            node = nodes[index]
            if node.status in {NodeStatus.COMPLETED, NodeStatus.SKIPPED}:
                index += 1
                continue
            if not self._dependencies_completed(node, statuses):
                return await self._abort(
                    recorder, node, graph.task_id, "Dependencies are not completed"
                )

            if deadline is not None and time.monotonic() > deadline:
                await self._record(recorder, "task.budget_exceeded", graph.task_id)
                return await self._abort(
                    recorder, node, graph.task_id, "Task budget exceeded (duration)"
                )

            outcome = await self._run_node(node, graph.task_id, handler, recorder)
            statuses[node.id] = outcome.status

            if outcome.status is NodeStatus.WAITING:
                await self._update_task_status(
                    graph.task_id,
                    TaskStatus.WAITING_APPROVAL,
                    recorder,
                )
                await self._record(
                    recorder,
                    "task.waiting_approval",
                    graph.task_id,
                    {"node_id": node.id, "type": node.type.value},
                )
                return TaskResult(
                    task_id=graph.task_id, status=TaskStatus.WAITING_APPROVAL
                )

            if outcome.status is NodeStatus.FAILED:
                await self._update_task_status(
                    graph.task_id, TaskStatus.FAILED, recorder
                )
                await self._record(recorder, "task.failed", graph.task_id)
                return TaskResult(
                    task_id=graph.task_id,
                    status=TaskStatus.FAILED,
                    error=outcome.error,
                )

            evaluation_status = (
                outcome.output.get("status")
                if outcome.status is NodeStatus.COMPLETED
                and node.type is NodeType.EVALUATION
                and isinstance(outcome.output, dict)
                else None
            )
            # Stop looping in two cases, not one. ``passed`` means the change is
            # green. ``not_verified``/``partially_verified`` means some commands
            # were withheld: another AGENT round cannot change that, so
            # retrying would burn the remaining budget to reach the same
            # answer. Both go straight to approval, which is where the decision
            # actually belongs.
            #
            # A withheld command that is *parked on a grant* does not reach
            # here at all — that path returns WAITING above — so these two are
            # the cases where no approval is pending and none is coming.
            if evaluation_status in {"passed", "not_verified", "partially_verified"}:
                index += 1
                while (
                    index < len(nodes)
                    and nodes[index].type in {NodeType.AGENT, NodeType.EVALUATION}
                ):
                    skipped = nodes[index]
                    statuses[skipped.id] = NodeStatus.SKIPPED
                    await self._skip_node(skipped, graph.task_id, recorder)
                    index += 1
                continue
            index += 1

        await self._update_task_status(
            graph.task_id, TaskStatus.COMPLETED, recorder
        )
        await self._record(recorder, "task.completed", graph.task_id)
        return TaskResult(task_id=graph.task_id, status=TaskStatus.COMPLETED)

    async def resume(
        self,
        graph: ExecutionGraph,
        *,
        handler: NodeHandler = None,
        recorder: Any | None = None,
        budget: TaskBudget | None = None,
    ) -> TaskResult:
        """Continue a graph parked in WAITING_APPROVAL after a human decision."""
        return await self.execute(
            graph, handler=handler, recorder=recorder, budget=budget
        )

    # -- node execution ------------------------------------------------------
    async def _run_node(
        self,
        node: ExecutionNode,
        task_id: str,
        handler: NodeHandler,
        recorder: Any | None,
    ) -> NodeResult:
        max_attempts = max(1, node.budget.max_attempts)
        current = node
        while True:
            NodeStateMachine.validate(current.status, NodeStatus.RUNNING)
            running = replace(
                current, status=NodeStatus.RUNNING, attempts=current.attempts + 1
            )
            await self._metadata.save_execution_node(running)
            await self._record(
                recorder,
                "node.started",
                task_id,
                {
                    "node_id": running.id,
                    "type": running.type.value,
                    "attempt": running.attempts,
                },
            )
            try:
                output = None
                if handler is not None:
                    async def invoke(node: ExecutionNode = running) -> Any:
                        result = handler(node)
                        return await result if hasattr(result, "__await__") else result

                    if running.budget.timeout_seconds > 0:
                        output = await asyncio.wait_for(
                            invoke(),
                            timeout=running.budget.timeout_seconds,
                        )
                    else:
                        output = await invoke()
            except Exception as exc:  # noqa: BLE001 - graph failures must update state
                error = f"{type(exc).__name__}: {exc}"
                if running.attempts < max_attempts:
                    await self._record(
                        recorder,
                        "node.retrying",
                        task_id,
                        {"node_id": running.id, "error": error},
                    )
                    current = replace(
                        running,
                        status=NodeStatus.PENDING,
                        metadata={**running.metadata, "last_error": error},
                    )
                    continue
                await self._fail(running, error)
                await self._record(
                    recorder,
                    "node.failed",
                    task_id,
                    {"node_id": running.id, "error": error},
                )
                return NodeResult(running.id, NodeStatus.FAILED, error=error)

            if isinstance(output, dict) and output.get("waiting"):
                waiting = replace(
                    running,
                    status=NodeStatus.WAITING,
                    metadata={**running.metadata, "output": output},
                )
                NodeStateMachine.validate(running.status, NodeStatus.WAITING)
                await self._metadata.save_execution_node(waiting)
                return NodeResult(waiting.id, NodeStatus.WAITING, output=output)

            completed = replace(
                running,
                status=NodeStatus.COMPLETED,
                metadata={**running.metadata, "output": output},
            )
            NodeStateMachine.validate(running.status, NodeStatus.COMPLETED)
            await self._metadata.save_execution_node(completed)
            await self._record(
                recorder,
                "node.completed",
                task_id,
                {"node_id": completed.id, "type": completed.type.value},
            )
            return NodeResult(completed.id, NodeStatus.COMPLETED, output=output)

    # -- state helpers -------------------------------------------------------
    async def _restore(self, graph: ExecutionGraph) -> tuple[ExecutionNode, ...]:
        """Overlay persisted node state onto a freshly compiled graph."""
        stored = {
            node.id: node
            for node in await self._metadata.list_execution_nodes(graph.task_id)
        }
        if not stored:
            return tuple(graph.nodes)
        restored: list[ExecutionNode] = []
        for node in graph.nodes:
            previous = stored.get(node.id)
            if previous is None:
                restored.append(node)
                continue
            restored.append(
                replace(
                    node,
                    status=previous.status,
                    attempts=previous.attempts,
                    metadata=dict(previous.metadata),
                )
            )
        return tuple(restored)

    async def _abort(
        self,
        recorder: Any | None,
        node: ExecutionNode,
        task_id: str,
        reason: str,
    ) -> TaskResult:
        await self._fail(node, reason)
        await self._record(
            recorder,
            "node.failed",
            task_id,
            {"node_id": node.id, "error": reason},
        )
        await self._update_task_status(task_id, TaskStatus.FAILED, recorder)
        await self._record(recorder, "task.failed", task_id)
        return TaskResult(task_id=task_id, status=TaskStatus.FAILED, error=reason)

    async def _fail(self, node: ExecutionNode, reason: str) -> None:
        NodeStateMachine.validate(node.status, NodeStatus.FAILED)
        failed = replace(
            node,
            status=NodeStatus.FAILED,
            metadata={**node.metadata, "error": reason},
        )
        await self._metadata.save_execution_node(failed)

    async def _skip_node(
        self,
        node: ExecutionNode,
        task_id: str,
        recorder: Any | None,
    ) -> None:
        skipped = replace(
            node,
            status=NodeStatus.SKIPPED,
            metadata={**node.metadata, "output": {"skipped": True}},
        )
        await self._metadata.save_execution_node(skipped)
        await self._record(
            recorder,
            "node.skipped",
            task_id,
            {"node_id": node.id, "type": node.type.value},
        )

    async def _update_task_status(
        self,
        task_id: str,
        target: TaskStatus,
        recorder: Any | None,
    ) -> None:
        current_task = await self._metadata.get_task(task_id)
        if current_task is not None:
            TaskStateMachine.validate(current_task.status, target)
        await self._metadata.update_task_status(task_id, target)
        await self._record(
            recorder,
            "task.status_changed",
            task_id,
            {
                "previous": (
                    current_task.status.value
                    if current_task is not None
                    else None
                ),
                "target": target.value,
            },
        )

    @staticmethod
    def _dependencies_completed(
        node: ExecutionNode, statuses: dict[str, NodeStatus]
    ) -> bool:
        return all(
            statuses.get(dep) in {NodeStatus.COMPLETED, NodeStatus.SKIPPED}
            for dep in node.dependencies
        )

    @staticmethod
    async def _record(
        recorder: Any | None,
        name: str,
        task_id: str,
        payload: dict | None = None,
    ) -> None:
        if recorder is None:
            return
        await recorder.record(
            TrajectoryEvent(name=name, task_id=task_id, payload=payload or {})
        )

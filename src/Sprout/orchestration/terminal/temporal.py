"""Temporal-backed orchestrator backend.

This backend keeps the existing execution-graph model but delegates scheduling,
retries, approvals, and durability to Temporal workflows and activities.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from Sprout.orchestration.models import ExecutionGraph
from Sprout.orchestration.temporal_codec import graph_to_dict
from Sprout.runtime.state import TaskStateMachine
from Sprout.task.models import TaskResult, TaskStatus


@dataclass(slots=True)
class TemporalConfig:
    host: str = "127.0.0.1:7233"
    namespace: str = "default"
    task_queue: str = "sprout-tasks"

    @classmethod
    def from_env(cls) -> TemporalConfig:
        return cls(
            host=os.getenv("TEMPORAL_HOST", "127.0.0.1:7233"),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "sprout-tasks"),
        )


class TemporalOrchestratorBackend:
    """Submit execution graphs to Temporal.

    The actual workflow/activity code lives in
    ``src/Sprout/orchestration/temporal_workflows.py`` and is executed by a
    Temporal worker process. This backend only performs client-side submission
    and result polling, so the CLI/runtime remain transport-agnostic.
    """

    def __init__(
        self,
        config: TemporalConfig | None = None,
        *,
        metadata: Any | None = None,
    ) -> None:
        self._config = config or TemporalConfig.from_env()
        self._metadata = metadata

    async def execute(
        self,
        graph: ExecutionGraph,
        *,
        handler=None,
        recorder=None,
        budget=None,
    ) -> TaskResult:
        from temporalio.client import Client
        from temporalio.common import WorkflowIDReusePolicy

        if self._metadata is not None:
            await self._transition_task(graph.task_id, TaskStatus.RUNNING)
        try:
            client = await Client.connect(
                self._config.host, namespace=self._config.namespace
            )
            handle = await client.start_workflow(
                "SproutExecutionWorkflow",
                graph_to_dict(graph),
                id=f"sprout-{graph.task_id}",
                task_queue=self._config.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
            result = await handle.result()
        except Exception as exc:  # noqa: BLE001 - unify Temporal failures into TaskResult
            if self._metadata is not None:
                await self._transition_task(graph.task_id, TaskStatus.FAILED)
            return TaskResult(
                task_id=graph.task_id,
                status=TaskStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(result, dict):
            if self._metadata is not None:
                await self._transition_task(graph.task_id, TaskStatus.FAILED)
            return TaskResult(
                task_id=graph.task_id,
                status=TaskStatus.FAILED,
                error=str(result),
            )
        try:
            status = TaskStatus(result.get("status", "failed"))
        except ValueError:
            status = TaskStatus.FAILED
        if self._metadata is not None:
            await self._transition_task(graph.task_id, status)
        return TaskResult(
            task_id=graph.task_id,
            status=status,
            error=result.get("error"),
        )

    async def _transition_task(self, task_id: str, target: TaskStatus) -> None:
        """Update task status without raising on already-settled states."""
        current = await self._metadata.get_task(task_id)
        if current is None:
            return
        try:
            TaskStateMachine.validate(current.status, target)
        except ValueError:
            return
        await self._metadata.update_task_status(task_id, target)


async def probe_temporal(config: TemporalConfig | None = None) -> dict[str, Any]:
    """Probe Temporal without requiring the Temporal CLI.

    The returned report is intentionally plain data so the CLI can format it
    for humans and tests can assert on it without touching the server.
    """
    from temporalio.api.enums.v1 import TaskQueueKind, TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import (
        DescribeNamespaceRequest,
        DescribeTaskQueueRequest,
        GetSystemInfoRequest,
    )
    from temporalio.client import Client
    from temporalio.service import RPCError, RPCStatusCode

    config = config or TemporalConfig.from_env()
    report: dict[str, Any] = {
        "host": config.host,
        "namespace": config.namespace,
        "task_queue": config.task_queue,
        "reachable": False,
        "server_version": None,
        "namespace_found": None,
        "workers": 0,
        "error": None,
    }
    try:
        client = await Client.connect(config.host, namespace=config.namespace, lazy=True)
        system = await client.workflow_service.get_system_info(GetSystemInfoRequest())
        report["reachable"] = True
        report["server_version"] = system.server_version
        try:
            await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=config.namespace)
            )
            report["namespace_found"] = True
        except RPCError as exc:
            report["namespace_found"] = exc.status != RPCStatusCode.NOT_FOUND
            if exc.status != RPCStatusCode.NOT_FOUND:
                report["error"] = str(exc)
        if report["namespace_found"]:
            try:
                queue = await client.workflow_service.describe_task_queue(
                    DescribeTaskQueueRequest(
                        namespace=config.namespace,
                        task_queue=TaskQueue(
                            name=config.task_queue,
                            kind=TaskQueueKind.TASK_QUEUE_KIND_NORMAL,
                        ),
                        task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                        include_task_queue_status=True,
                        report_pollers=True,
                    )
                )
                report["workers"] = len(queue.pollers)
            except RPCError as exc:
                report["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report

"""Temporal workflow and activity definitions for Sprout orchestration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

from Sprout.orchestration.temporal_codec import node_from_dict

_activity_runtime = None
_VERIFY_LOOP_NODE_TYPES = frozenset({"agent", "evaluation"})


def set_activity_runtime(runtime) -> None:
    global _activity_runtime
    _activity_runtime = runtime


@activity.defn
async def run_sprout_node(node: dict[str, Any]) -> dict[str, Any]:
    """Execute one real project node through the worker's Runtime."""
    if _activity_runtime is None:
        raise RuntimeError("Sprout worker has no runtime configured")
    return await _activity_runtime.execute_node(node_from_dict(node))


@workflow.defn
class SproutExecutionWorkflow:
    @workflow.run
    async def run(self, graph: dict[str, Any]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        nodes = list(graph.get("nodes", []))
        index = 0
        while index < len(nodes):
            node = nodes[index]
            if node.get("status") == "completed":
                results.append(
                    {
                        "node_id": node.get("id"),
                        "status": "completed",
                        "skipped": True,
                    }
                )
                index += 1
                continue
            try:
                result = await workflow.execute_activity(
                    run_sprout_node,
                    node,
                    start_to_close_timeout=timedelta(
                        seconds=float(node.get("budget", {}).get("timeout_seconds", 0))
                        or 3600
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - workflow must return a structured result
                error = f"{type(exc).__name__}: {exc}"
                results.append(
                    {
                        "node_id": node.get("id"),
                        "status": "failed",
                        "error": error,
                    }
                )
                return {"status": "failed", "nodes": results, "error": error}
            results.append(result)
            output = result.get("output") if isinstance(result, dict) else None
            if isinstance(output, dict) and output.get("waiting"):
                return {
                    "status": "waiting_approval",
                    "node_id": result.get("node_id"),
                    "nodes": results,
                }
            if (
                node.get("type") == "evaluation"
                and isinstance(output, dict)
                and output.get("status") == "passed"
            ):
                index = _skip_verify_loop(nodes, index + 1, results)
                continue
            index += 1
        return {"status": "completed", "nodes": results}


def _skip_verify_loop(
    nodes: list[dict[str, Any]], start: int, results: list[dict[str, Any]]
) -> int:
    """Mark the remaining edit/test rounds skipped after a green evaluation."""
    index = start
    while index < len(nodes) and nodes[index].get("type") in _VERIFY_LOOP_NODE_TYPES:
        results.append(
            {
                "node_id": nodes[index].get("id"),
                "status": "skipped",
                "skipped": True,
            }
        )
        index += 1
    return index


@workflow.defn
class SproutTaskWorkflow:
    @workflow.run
    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task.get("id", ""),
            "status": "queued",
        }


@activity.defn
async def run_growth_automation(workspace_id: str, trajectory_dir: str) -> dict[str, Any]:
    if _activity_runtime is None:
        raise RuntimeError("Sprout worker has no runtime configured")
    from Sprout.evolution.automation import GrowthAutomation

    metadata = _activity_runtime.storage.metadata
    if metadata is None:
        raise RuntimeError("MetadataStore is not configured")
    automation = GrowthAutomation(
        metadata, workspace_id, trajectory_dir, runtime=_activity_runtime
    )
    return await automation.run_once()


@workflow.defn
class SproutGrowthWorkflow:
    @workflow.run
    async def run(self, workspace_id: str, trajectory_dir: str) -> dict[str, Any]:
        return await workflow.execute_activity(
            run_growth_automation,
            (workspace_id, trajectory_dir),
            start_to_close_timeout=3600,
        )


@workflow.defn
class SproutGatewayWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"gateway": payload.get("transport"), "status": "submitted"}

"""Minimal runtime-backed task replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from Sprout.task.models import TaskStatus
from Sprout.trajectory.models import ArtifactSnapshot

if TYPE_CHECKING:
    from Sprout.runtime.runtime import Runtime


@dataclass(frozen=True, slots=True)
class ReplayResult:
    task_id: str
    status: TaskStatus
    error: str | None = None
    artifact_snapshot: ArtifactSnapshot | None = None


class ReplayRunner:
    """Re-executes a stored task through the current Runtime."""

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime

    async def run(
        self,
        task_id: str,
        *,
        artifact_snapshot: ArtifactSnapshot | None = None,
    ) -> ReplayResult:
        task = await self._runtime.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        result = await self._runtime.execute(task, artifact_snapshot=artifact_snapshot)
        return ReplayResult(
            task_id=task_id,
            status=result.status,
            error=result.error,
            artifact_snapshot=artifact_snapshot,
        )

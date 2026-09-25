"""Append-only JSONL trajectory recorder."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from Sprout.trajectory.models import TrajectoryEvent

logger = logging.getLogger("sprout.trajectory")

#: Task ids become file names under ``~/.sprout/data/sprout_trajectory``, so anything that could
#: escape that directory has to be refused (AUTHZ §6.4).
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_trajectory_name(task_id: str) -> str:
    """Validate a task id used as a trajectory file name.

    Rejects separators and traversal instead of sanitizing them: silently
    rewriting an id could make two different tasks share one trajectory file.
    """
    if not task_id or task_id in {".", ".."} or not _SAFE_TASK_ID.match(task_id):
        raise ValueError(f"Unsafe task id for a trajectory file: {task_id!r}")
    return task_id


def trajectory_path(directory: str | Path, task_id: str) -> Path:
    """The validated trajectory file for one task."""
    return Path(directory) / f"{safe_trajectory_name(task_id)}.jsonl"


class JsonlTrajectoryRecorder:
    """Writes trajectory events to an append-only JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, event: TrajectoryEvent) -> None:
        payload = {
            "event_id": event.id,
            "name": event.name,
            "task_id": event.task_id,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": dict(event.payload),
        }
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        await asyncio.to_thread(self._append, line)

    async def read_all(self) -> list[TrajectoryEvent]:
        return await asyncio.to_thread(self._read_all)

    def _append(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _read_all(self) -> list[TrajectoryEvent]:
        """Read every well-formed event, skipping lines that cannot be parsed.

        A trajectory file is appended to while the task runs, so a process killed
        mid-write leaves a half-line at the end — and an empty line is always
        possible. Neither is corruption of the *events*: it is a partial last
        record, and every other JSONL reader here already tolerates it
        (``SecurityAuditLog.read_entries``, ``SkillIndex.load``).

        Raising instead was not a local failure. The caller
        (``TrajectoryGrowthService.collect``) walks every trajectory file with no
        guard, so one truncated file aborted the whole collection pass and every
        other task's trajectory went unread that run.
        """
        if not self._path.exists():
            return []

        events: list[TrajectoryEvent] = []
        skipped = 0
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(data, dict):
                skipped += 1
                continue
            try:
                events.append(
                    TrajectoryEvent(
                        id=data["event_id"],
                        name=data["name"],
                        task_id=data["task_id"],
                        payload=dict(data.get("payload", {})),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # A parseable object missing required keys is not a trajectory
                # event; skip it rather than losing the rest of the file.
                skipped += 1
        if skipped:
            logger.warning(
                "Skipped %d unreadable line(s) in trajectory %s", skipped, self._path
            )
        return events

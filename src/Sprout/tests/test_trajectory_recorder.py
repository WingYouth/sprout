"""Reading a trajectory file must survive a partial write.

A trajectory is appended to while the task runs, so a process killed mid-write
leaves a half line at the end of the file. The reader raised ``JSONDecodeError``
on it — and because the caller
(:meth:`~Sprout.evolution.trajectory_growth.TrajectoryGrowthService.collect`)
walks every trajectory file with no guard, one truncated file aborted the whole
collection pass and every *other* task's trajectory went unread that run.

Every other JSONL reader in this codebase already tolerates this
(``SecurityAuditLog.read_entries``, ``SkillIndex.load``); this one did not.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from Sprout.trajectory.recorder import JsonlTrajectoryRecorder, trajectory_path


def _event(event_id: str, name: str = "step", task_id: str = "task-1") -> str:
    return json.dumps(
        {"event_id": event_id, "name": name, "task_id": task_id, "payload": {"n": 1}},
        ensure_ascii=False,
    )


def _read(path: Path) -> list:
    return asyncio.run(JsonlTrajectoryRecorder(path).read_all())


def test_a_well_formed_file_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(_event("1") + "\n" + _event("2") + "\n", encoding="utf-8")

    events = _read(path)

    assert [event.id for event in events] == ["1", "2"]


def test_a_truncated_last_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    """The case a killed process produces: a half-written final record."""
    path = tmp_path / "t.jsonl"
    path.write_text(
        _event("1") + "\n" + _event("2") + "\n" + '{"event_id":"3","name":"st',
        encoding="utf-8",
    )

    events = _read(path)

    assert [event.id for event in events] == ["1", "2"]


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(_event("1") + "\n\n" + _event("2") + "\n", encoding="utf-8")

    assert [event.id for event in _read(path)] == ["1", "2"]


def test_a_parseable_line_missing_keys_is_skipped(tmp_path: Path) -> None:
    """Valid JSON is not automatically a trajectory event."""
    path = tmp_path / "t.jsonl"
    path.write_text(
        _event("1") + "\n" + '{"event_id":"2"}\n' + _event("3") + "\n",
        encoding="utf-8",
    )

    assert [event.id for event in _read(path)] == ["1", "3"]


def test_a_non_object_line_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("[1, 2, 3]\n" + _event("1") + "\n", encoding="utf-8")

    assert [event.id for event in _read(path)] == ["1"]


def test_an_entirely_unreadable_file_reads_as_empty(tmp_path: Path) -> None:
    """No usable lines is "no trajectory", not a crash."""
    path = tmp_path / "t.jsonl"
    path.write_text("not json at all\n{also broken\n", encoding="utf-8")

    assert _read(path) == []


def test_a_missing_file_reads_as_empty(tmp_path: Path) -> None:
    assert _read(tmp_path / "absent.jsonl") == []


def test_the_payload_survives_the_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(_event("1") + "\n", encoding="utf-8")

    events = _read(path)

    assert events[0].payload == {"n": 1}
    assert events[0].task_id == "task-1"


# -- the name is validated, not sanitized ------------------------------------


def test_a_task_id_cannot_escape_the_trajectory_directory(tmp_path: Path) -> None:
    """Rejected outright: rewriting an id could make two tasks share a file."""
    for unsafe in ("../escape", "a/b", "..", "", "a b"):
        try:
            trajectory_path(tmp_path, unsafe)
        except ValueError:
            continue
        raise AssertionError(f"{unsafe!r} should have been refused")


def test_a_plain_task_id_is_accepted(tmp_path: Path) -> None:
    assert trajectory_path(tmp_path, "task-1") == tmp_path / "task-1.jsonl"

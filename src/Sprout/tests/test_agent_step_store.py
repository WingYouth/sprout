"""Tests for the agent step recorder's storage contract."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from Sprout.agent.step_store import AgentStepStore
from Sprout.storage.topology import STORAGE_DATABASES


class _Call:
    """Minimal stand-in for the agent loop's tool-call object."""

    def __init__(self, call_id: str, name: str, arguments: dict) -> None:
        self.id = call_id
        self.name = name
        self.arguments = arguments


def test_default_path_is_a_registered_authority() -> None:
    # Steps must land in the runtime-coordination authority, never a side file.
    default = AgentStepStore.__init__.__defaults__
    assert default == (None,)
    from Sprout.agent import step_store

    assert step_store._DEFAULT_PATH.name == "sprout_core.db"
    assert step_store._DEFAULT_PATH.name in {d.filename for d in STORAGE_DATABASES}


def test_record_writes_a_row(tmp_path: Path) -> None:
    store = AgentStepStore(path=tmp_path / "sprout_core.db")
    store.record(
        session_id="s-1",
        step=3,
        content="thinking",
        tool_calls=[_Call("c1", "read_file", {"path": "x.py"})],
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    store.close()

    con = sqlite3.connect(tmp_path / "sprout_core.db")
    try:
        row = con.execute(
            "SELECT session_id, step, content, tool_calls_json, total_tokens "
            "FROM agent_steps"
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    session_id, step, content, calls_json, total = row
    assert (session_id, step, content, total) == ("s-1", 3, "thinking", 15)
    assert json.loads(calls_json) == [
        {"id": "c1", "name": "read_file", "arguments": {"path": "x.py"}}
    ]


def test_reopening_the_same_path_keeps_rows(tmp_path: Path) -> None:
    path = tmp_path / "sprout_core.db"
    first = AgentStepStore(path=path)
    first.record(
        session_id="s-1",
        step=1,
        content=None,
        tool_calls=[],
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )
    first.close()

    second = AgentStepStore(path=path)
    second.record(
        session_id="s-2",
        step=1,
        content=None,
        tool_calls=[],
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )
    second.close()

    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT COUNT(*) FROM agent_steps").fetchone()[0] == 2
    finally:
        con.close()

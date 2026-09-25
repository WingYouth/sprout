"""A queued task's approval must reach the operator, or the task dies quietly.

Work started by ``/task`` — or by granting workspace consent — runs on the
background worker and returns immediately. When it reaches a node that needs
permission it parks, and the approval belongs to a task id that no reply
carries.

``_handle_cli_approval_prompt`` reads ``approval_ids`` off one reply's metadata,
so it can only ever ask about the turn in front of it. A parked task's question
therefore had no route to the terminal: the operator saw an agent that had gone
quiet, the task sat until its grant expired an hour later, and tasks
accumulated in ``waiting_approval`` as the user rephrased the same request.

``_report_parked_tasks`` is the route, and these tests pin it: a parked task is
found by the session that asked, the report names what would unblock it, and —
the property that matters most — it reports without deciding anything. Parking
is the safety mechanism, so a notice that resolved what it was reporting would
defeat the thing it exists to protect.

The other half is clearance. Cancelling a task settles the task but leaves its
approval ``pending``, so the report keeps offering a question about work that
can no longer act on the answer; ``resolve_orphaned_approvals`` retires those.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Sprout.cli.commands import chat
from Sprout.config.loader import default_settings
from Sprout.llm.echo import EchoModel
from Sprout.runtime.factory import create_runtime
from Sprout.task.models import TaskStatus


def _runtime(tmp_path: Path):
    settings = default_settings()
    settings.model.provider = "echo"
    settings.model.model = "echo-1"
    db = (tmp_path / "meta.db").as_posix()
    settings.storage.operational = f"sqlite:///{(tmp_path / 'op.db').as_posix()}"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{db}"
    settings.storage.session = f"sqlite:///{db}"
    settings.storage.trajectory_dir = str(tmp_path / "traj")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "audit.jsonl")
    runtime = create_runtime(settings)
    runtime.models.register(EchoModel(), default=True)
    return runtime


async def _waiting_task(
    runtime,
    tmp_path: Path,
    *,
    session_id: str = "session-1",
    instruction: str = "a parked task",
):
    """A real task record parked in WAITING_APPROVAL, owned by a session."""
    from Sprout.task.models import Task

    root = tmp_path / f"ws-{abs(hash(instruction)) % 100000}"
    root.mkdir(exist_ok=True)
    workspace = await runtime.open_workspace(root)
    task = Task(
        workspace_id=workspace.id,
        instruction=instruction,
        metadata={"session_id": session_id},
    )
    await runtime.storage.metadata.save_task(task)
    await runtime.storage.metadata.update_task_status(task.id, TaskStatus.WAITING_APPROVAL)
    return task


async def _parked_approval(runtime, task, *, tool="process_run"):
    """The grant a parked evaluation node raises."""
    return await runtime.approvals.request(
        tool,
        {"action": "verification_commands", "task_id": task.id},
        task_id=task.id,
        requested_by="cli-user",
        source="interactive",
        single_use=False,
    )


# -- the report reaches the operator ------------------------------------------


@pytest.mark.asyncio
async def test_a_parked_task_is_found_by_its_session(tmp_path) -> None:
    """The lookup the report is built on, and the bug it was written for."""
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path, session_id="s-1")

    found = await runtime.parked_tasks_for_session("s-1")

    assert [item.id for item in found] == [task.id]
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_task_is_not_reported_to_another_session(tmp_path) -> None:
    """A detached task must not surface in a conversation that did not ask."""
    runtime = _runtime(tmp_path)
    await _waiting_task(runtime, tmp_path, session_id="s-1")

    assert await runtime.parked_tasks_for_session("s-2") == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_settled_task_is_not_reported(tmp_path) -> None:
    """Only work still waiting on a human belongs in the report."""
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path)
    await runtime.storage.metadata.update_task_status(task.id, TaskStatus.COMPLETED)

    assert await runtime.parked_tasks_for_session("session-1") == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_report_names_the_approval_that_unblocks_it(tmp_path) -> None:
    """ "Waiting on you" is useless without what to do about it."""
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path)
    record = await _parked_approval(runtime, task)

    kind, handle = await runtime.task_progress(task)

    assert kind == "approval"
    assert handle == record.id
    await runtime.stop()


@pytest.mark.asyncio
async def test_reporting_decides_nothing(tmp_path, capsys) -> None:
    """The notice must not resolve what it reports.

    Parking is the safety property here. A report that quietly approved the
    task would remove the human decision it exists to surface — the worst
    possible way to "fix" a task that nobody was told about.
    """
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path)
    record = await _parked_approval(runtime, task)

    await chat._report_parked_tasks(runtime, "session-1")

    after = await runtime.approvals.store.get_approval(record.id)
    assert after is not None and after.status.value == "pending", (
        "the report decided the approval it was describing"
    )
    reloaded = await runtime.storage.metadata.get_task(task.id)
    assert reloaded.status is TaskStatus.WAITING_APPROVAL
    await runtime.stop()


@pytest.mark.asyncio
async def test_reporting_stays_quiet_when_nothing_is_parked(tmp_path, capsys) -> None:
    """The common case must print nothing, or every turn gains a notice."""
    runtime = _runtime(tmp_path)

    await chat._report_parked_tasks(runtime, "session-1")

    assert capsys.readouterr().out.strip() == ""
    await runtime.stop()


@pytest.mark.asyncio
async def test_status_handles_distinct_approval_gates_in_one_interaction(
    monkeypatch, capsys
) -> None:
    """Approving verification proceeds directly to reviewing the resulting diff."""
    from types import SimpleNamespace

    monkeypatch.setattr(chat.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    class _Select:
        async def ask_async(self):
            return "approve"

    monkeypatch.setattr(chat.questionary, "select", lambda *_args, **_kwargs: _Select())
    record = SimpleNamespace(
        id="approval-1",
        tool="process_run",
        expires_at=None,
        resource_scope="workspace",
        task_id="task-1",
        source="cli",
        requested_by="operator",
        approval_class="",
        action_summary='{"command":"pytest","args":["-q"]}',
    )
    proposal = SimpleNamespace(
        id="proposal-1",
        files_changed=("src/change.py",),
        diffs=(SimpleNamespace(path="src/change.py", diff_text="+answer = 42"),),
        test_results=(),
    )
    task = SimpleNamespace(
        id="task-1", status=SimpleNamespace(value="waiting_approval")
    )

    class _Store:
        async def get_approval(self, _approval_id):
            return record

    class _Runtime:
        approvals = SimpleNamespace(store=_Store())
        gate = "approval"

        async def get_task(self, _task_id):
            return SimpleNamespace(
                id="task-1", status=SimpleNamespace(value=self.status)
            )

        async def task_progress(self, _task):
            if self.gate == "approval":
                return "approval", record.id
            if self.gate == "proposal":
                return "proposal", proposal.id
            return "", ""

        async def decide_approval(self, *_args, **_kwargs):
            self.gate = "proposal"

        async def find_change_proposal(self, _proposal_id):
            return proposal

        async def approve_change_proposal(self, *_args, **_kwargs):
            self.gate = "done"
            self.status = "completed"

    runtime = _Runtime()
    runtime.status = "waiting_approval"
    await chat._approve_task_gates(runtime, task, "operator")

    printed = capsys.readouterr().out
    assert "sprout approvals approve approval-1" in printed
    assert "sprout project approve proposal-1" in printed
    assert "Diff src/change.py" in printed
    assert runtime.status == "completed"


@pytest.mark.asyncio
async def test_status_requires_explicit_choice_to_apply_after_failed_verification(
    monkeypatch, capsys
) -> None:
    from types import SimpleNamespace

    from Sprout.cli.approval_prompt import APPROVE_WITH_FAILURES

    monkeypatch.setattr(chat.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    captured = {}

    class _Select:
        async def ask_async(self):
            return APPROVE_WITH_FAILURES

    def _select(_message, *, choices, **_kwargs):
        captured["choices"] = choices
        return _Select()

    monkeypatch.setattr(chat.questionary, "select", _select)
    proposal = SimpleNamespace(
        id="proposal-failed",
        files_changed=("src/change.py",),
        diffs=(),
        test_results=(SimpleNamespace(failed=True),),
    )
    task = SimpleNamespace(
        id="task-failed", status=SimpleNamespace(value="waiting_approval")
    )

    class _Runtime:
        status = "waiting_approval"

        async def get_task(self, _task_id):
            return SimpleNamespace(
                id=task.id, status=SimpleNamespace(value=self.status)
            )

        async def task_progress(self, _task):
            return ("proposal", proposal.id) if self.status == "waiting_approval" else ("", "")

        async def find_change_proposal(self, _proposal_id):
            return proposal

        async def approve_change_proposal(self, _proposal_id, **kwargs):
            captured["approve_kwargs"] = kwargs
            self.status = "completed"

    runtime = _Runtime()
    await chat._approve_task_gates(runtime, task, "operator")

    assert APPROVE_WITH_FAILURES in [choice.value for choice in captured["choices"]]
    assert captured["approve_kwargs"]["allow_failing_tests"] is True
    assert "sprout project apply" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_background_watcher_reports_gate_and_returns_agent_reply(
    monkeypatch, capsys
) -> None:
    """Detached work reports safely in the active chat and includes its answer."""
    from types import SimpleNamespace

    states = iter(("waiting_approval", "completed"))
    node = SimpleNamespace(
        type=SimpleNamespace(value="agent"),
        metadata={"output": {"content": "Implemented the requested change."}},
    )
    task = SimpleNamespace(id="task-1", status=SimpleNamespace(value="waiting_approval"))

    class _Metadata:
        async def list_execution_nodes(self, _task_id):
            return [node]

    class _Runtime:
        _started = True
        storage = SimpleNamespace(metadata=_Metadata())

        async def get_task(self, _task_id):
            task.status = SimpleNamespace(value=next(states))
            return task

        async def task_progress(self, _task):
            return "approval", "approval-1"

    async def _no_sleep(_seconds):
        return None

    async def _in_terminal(callback):
        callback()

    monkeypatch.setattr(chat.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(chat, "run_in_terminal", _in_terminal)
    await chat._watch_background_task(_Runtime(), "task-1")

    printed = capsys.readouterr().out
    assert "sprout approvals approve approval-1" in printed
    assert "Implemented the requested change." in printed


@pytest.mark.asyncio
async def test_reporting_without_a_session_is_a_no_op(tmp_path, capsys) -> None:
    """The first turn has no session id yet; that is not an error."""
    runtime = _runtime(tmp_path)
    await _waiting_task(runtime, tmp_path)

    await chat._report_parked_tasks(runtime, None)

    assert capsys.readouterr().out.strip() == ""
    await runtime.stop()


# -- clearing a task whose question has been answered --------------------------


@pytest.mark.asyncio
async def test_cancelling_clears_the_open_approval(tmp_path) -> None:
    """A cancelled task must not keep asking about itself.

    ``cancel_task`` stops the task, but its approval record stays ``pending`` —
    so the report keeps offering a question about work that can no longer act
    on the answer. ``resolve_orphaned_approvals`` retires those.
    """
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path)
    await _parked_approval(runtime, task)

    await runtime.cancel_task(task.id)
    cleared = await runtime.resolve_orphaned_approvals(task.id)

    assert cleared == 1
    still_open = [
        record
        for record in await runtime.pending_approvals()
        if getattr(record, "task_id", "") == task.id
    ]
    assert not still_open, "a cancelled task was still asking for a decision"
    await runtime.stop()


@pytest.mark.asyncio
async def test_clearing_one_task_leaves_another_task_alone(tmp_path) -> None:
    """Clearing one task's questions must not decide another task's."""
    runtime = _runtime(tmp_path)
    mine = await _waiting_task(runtime, tmp_path, instruction="mine")
    other = await _waiting_task(runtime, tmp_path, instruction="other")
    await _parked_approval(runtime, mine)
    keep = await _parked_approval(runtime, other, tool="cli_tool_run")

    await runtime.cancel_task(mine.id)
    cleared = await runtime.resolve_orphaned_approvals(mine.id)

    assert cleared == 1
    survivor = await runtime.approvals.store.get_approval(keep.id)
    assert survivor is not None and survivor.status.value == "pending"
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_cancelled_task_drops_out_of_the_report(tmp_path) -> None:
    """End to end: cancel, clear, and it is no longer announced."""
    runtime = _runtime(tmp_path)
    task = await _waiting_task(runtime, tmp_path)
    await _parked_approval(runtime, task)

    await runtime.cancel_task(task.id)
    await runtime.resolve_orphaned_approvals(task.id)

    assert await runtime.parked_tasks_for_session("session-1") == []
    await runtime.stop()

"""``sprout project task-cancel``: retiring a task that is parked or running.

There was no supported way to do this at all. Approvals could be decided and
proposals rejected, but a task sitting on either gate had no exit — the only
cancellation in the codebase was the private ``_cancel_task_after_rejection``,
reachable only by rejecting a proposal. Tasks accumulated in ``waiting_approval``
with nothing an operator could run to clear them.

The choice this file pins is *cancel, not delete*: the task row stays, because
the execution nodes, change proposals and audit records all cite its id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from Sprout.cli.app import app
from Sprout.config.loader import load_settings
from Sprout.gateway.project_gateway import ProjectGateway
from Sprout.runtime.factory import create_runtime
from Sprout.runtime.state import TaskStateMachine
from Sprout.task.models import TaskStatus


def _sandbox_config(tmp_path: Path) -> Path:
    """A sprout.toml whose every lane — audit included — lands in ``tmp_path``."""
    data = tmp_path / "data"
    config = tmp_path / "sprout.toml"
    config.write_text(
        "[storage]\n"
        f'operational = "sqlite:///{(data / "runtime.db").as_posix()}"\n'
        f'knowledge = "sqlite:///{(data / "knowledge.db").as_posix()}"\n'
        f'metadata = "sqlite:///{(data / "sema.db").as_posix()}"\n'
        f'session = "sqlite:///{(data / "session.db").as_posix()}"\n'
        f'blobs_dir = "{(data / "media").as_posix()}"\n'
        f'trajectory_dir = "{(data / "trajectory").as_posix()}"\n'
        "\n"
        "[storage.observations]\n"
        f'dsn = "sqlite:///{(data / "observations.db").as_posix()}"\n'
        "\n"
        "[model]\n"
        'provider = "echo"\n'
        'model = "echo-1"\n'
        "\n"
        "[security.audit]\n"
        f'path = "{(data / "audit" / "security.jsonl").as_posix()}"\n',
        encoding="utf-8",
    )
    return config


async def _gateway(tmp_path: Path) -> ProjectGateway:
    runtime = create_runtime(load_settings(str(_sandbox_config(tmp_path))))
    await runtime.start()
    return ProjectGateway(runtime, transport="cli", default_user="cli-user")


async def _parked_task(gateway: ProjectGateway, tmp_path: Path, status: TaskStatus):
    """A task sitting in ``status``, with a workspace, as the pipeline leaves it."""
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    workspace = await gateway.open_workspace(str(root))
    task = await gateway.create_task(workspace.id, "修复一个不存在的问题")
    await gateway._runtime.storage.metadata.update_task_status(task.id, status)
    return await gateway._runtime.get_task(task.id)


# -- the state machine is the contract --------------------------------------------


async def test_a_parked_task_can_be_cancelled(tmp_path: Path) -> None:
    gateway = await _gateway(tmp_path)
    task = await _parked_task(gateway, tmp_path, TaskStatus.WAITING_APPROVAL)

    cancelled = await gateway.cancel_task(task.id)

    assert cancelled.status is TaskStatus.CANCELLED


async def test_a_running_task_can_be_cancelled(tmp_path: Path) -> None:
    """The stuck case: a task whose evaluation node never settles."""
    gateway = await _gateway(tmp_path)
    task = await _parked_task(gateway, tmp_path, TaskStatus.RUNNING)

    cancelled = await gateway.cancel_task(task.id)

    assert cancelled.status is TaskStatus.CANCELLED


async def test_cancelling_keeps_the_row_and_what_cites_it(tmp_path: Path) -> None:
    """The reason this is a status change and not a delete."""
    gateway = await _gateway(tmp_path)
    task = await _parked_task(gateway, tmp_path, TaskStatus.WAITING_APPROVAL)
    nodes_before = len(
        await gateway._runtime.storage.metadata.list_execution_nodes(task.id)
    )
    tasks_before = len(await gateway._runtime.list_tasks())

    await gateway.cancel_task(task.id)

    still_there = await gateway._runtime.get_task(task.id)
    assert still_there is not None, "the task row must survive its own cancellation"
    assert still_there.status is TaskStatus.CANCELLED
    # Asserted against the count as well as the lookup: get_task alone would
    # still pass if a *different* row answered for the id, and the count is what
    # a delete would move.
    assert len(await gateway._runtime.list_tasks()) == tasks_before
    nodes_after = len(
        await gateway._runtime.storage.metadata.list_execution_nodes(task.id)
    )
    assert nodes_after == nodes_before


@pytest.mark.parametrize(
    "settled",
    [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ROLLED_BACK],
)
async def test_a_closed_task_is_refused_not_silently_accepted(
    tmp_path: Path, settled: TaskStatus
) -> None:
    """The statuses with no exit must not be overwritten by a later cancel."""
    gateway = await _gateway(tmp_path)
    task = await _parked_task(gateway, tmp_path, settled)

    with pytest.raises(ValueError, match="cannot be cancelled"):
        await gateway.cancel_task(task.id)

    unchanged = await gateway._runtime.get_task(task.id)
    assert unchanged.status is settled


async def test_a_failed_task_is_cancellable(tmp_path: Path) -> None:
    """Not an oversight: ``FAILED`` has an exit (``RETRYING``), so it is not closed.

    Worth pinning because "failed means finished" is the intuitive reading, and
    the state machine says otherwise.
    """
    assert TaskStateMachine.can_transition(TaskStatus.FAILED, TaskStatus.CANCELLED)
    gateway = await _gateway(tmp_path)
    task = await _parked_task(gateway, tmp_path, TaskStatus.FAILED)

    cancelled = await gateway.cancel_task(task.id)

    assert cancelled.status is TaskStatus.CANCELLED


async def test_every_parked_status_is_actually_cancellable() -> None:
    """Guard: a new parked status added to the enum must still be cancellable."""
    parked = [
        status
        for status in TaskStatus
        if TaskStateMachine.can_transition(status, TaskStatus.CANCELLED)
    ]
    assert TaskStatus.WAITING_APPROVAL in parked
    assert TaskStatus.WAITING_RESOURCE in parked
    assert TaskStatus.RUNNING in parked


# -- reaching the CLI ---------------------------------------------------------------


async def test_an_unknown_task_id_is_reported_not_crashed(tmp_path: Path) -> None:
    gateway = await _gateway(tmp_path)

    with pytest.raises(LookupError, match="Task not found"):
        await gateway.cancel_task("no-such-task")


async def test_an_ambiguous_prefix_is_refused(tmp_path: Path) -> None:
    """Prefixes are convenient until two tasks collide; then guessing is wrong."""
    gateway = await _gateway(tmp_path)
    a = await _parked_task(gateway, tmp_path, TaskStatus.WAITING_APPROVAL)
    b = await _parked_task(gateway, tmp_path, TaskStatus.WAITING_APPROVAL)
    # Force a shared prefix rather than hoping the uuid4s happen to collide.
    shared = "deadbeef"
    metadata = gateway._runtime.storage.metadata
    await metadata.save_task(_with_id(a, f"{shared}-0000"))
    await metadata.save_task(_with_id(b, f"{shared}-1111"))

    with pytest.raises(LookupError, match="matches 2 tasks"):
        await gateway.cancel_task(shared)


def _with_id(task, new_id: str):
    from dataclasses import replace

    return replace(task, id=new_id)


def test_task_cancel_is_registered_and_documents_itself() -> None:
    result = CliRunner().invoke(app, ["project", "task-cancel", "--help"])

    assert result.exit_code == 0
    assert "--reason" in result.stdout


def test_project_help_lists_task_cancel() -> None:
    result = CliRunner().invoke(app, ["project", "--help"])

    assert result.exit_code == 0
    assert "task-cancel" in result.stdout

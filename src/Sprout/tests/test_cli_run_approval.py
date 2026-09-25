"""A CLI invocation needs one human approval and must retain process denial."""

from __future__ import annotations

import sys
from pathlib import Path

from Sprout.execution.process_broker import ProcessBroker
from Sprout.security.layer import SecurityLayer
from Sprout.storage.local.memory import MemoryOperationalStore
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.system_tools import CliRunTool


def _layer() -> SecurityLayer:
    """A real security layer, so the broker's decision is the real one."""
    return SecurityLayer.from_settings(_settings(), store=MemoryOperationalStore())


def _settings():
    from Sprout.config.defaults import default_settings

    return default_settings().security


def _broker(layer: SecurityLayer) -> ProcessBroker:
    return ProcessBroker(
        layer.policy_engine,
        commands=layer.commands,
        secrets=layer.secrets,
        audit=layer.audit,
        approvals=layer.approvals,
    )


async def _run_command(tmp_path: Path, tool: CliRunTool, *, task_id: str, source: str):
    """Drive the tool through ``ToolExecutor``, as the agent loop does."""
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(
        tools=registry,
        policy=_layer().tool_policy,
        approvals=tool._process_broker._approvals,
    )
    return await executor.execute(
        "cli_tool_run",
        {"command": sys.executable, "args": ["-c", "print(1)"], "cwd": str(tmp_path)},
        task_id=task_id,
        source=source,
    )


async def test_one_approval_runs_cli_command_without_a_second_prompt(
    tmp_path: Path,
) -> None:
    """The exact outer CLI grant is carried into the process broker."""
    layer = _layer()
    broker = _broker(layer)
    tool = CliRunTool(
        secrets=layer.secrets,
        allowed_roots=(tmp_path,),
        process_broker=broker,
    )
    manager = layer.approvals

    first = await _run_command(tmp_path, tool, task_id="t1", source="interactive")
    assert first.approval_id, "the tool layer must ask first"
    await manager.decide(first.approval_id, True, decided_by="cli", channel="cli")

    second = await _run_command(tmp_path, tool, task_id="t1", source="interactive")
    assert second.approval_id is None, "the broker must not repeat the same approval"
    assert second.ok, f"the approved command did not run: {second.error!r}"


async def test_the_broker_receives_the_calling_task_id(tmp_path: Path) -> None:
    """A task-scoped grant only matches if the task id survives the hand-off."""
    layer = _layer()
    broker = _broker(layer)
    seen: dict[str, str] = {}
    original = broker.run

    async def spy(*args, **kwargs):
        seen["task_id"] = kwargs.get("task_id", "")
        seen["source"] = kwargs.get("source", "")
        seen["requested_by"] = kwargs.get("requested_by", "")
        return await original(*args, **kwargs)

    broker.run = spy  # type: ignore[method-assign]
    tool = CliRunTool(
        secrets=layer.secrets, allowed_roots=(tmp_path,), process_broker=broker
    )

    # Answer the tool prompt; the broker receives the caller identity and grant.
    first = await _run_command(tmp_path, tool, task_id="task-abc", source="interactive")
    await layer.approvals.decide(first.approval_id, True, decided_by="cli", channel="cli")
    await _run_command(tmp_path, tool, task_id="task-abc", source="interactive")

    assert seen["task_id"] == "task-abc", "the broker saw no task id"
    assert seen["source"] == "interactive"
    assert seen["requested_by"], "the broker saw no requester"


async def test_an_unapproved_cli_run_still_requires_approval(
    tmp_path: Path,
) -> None:
    """The model cannot provide the server-injected approval context."""
    layer = _layer()
    broker = _broker(layer)
    tool = CliRunTool(
        secrets=layer.secrets, allowed_roots=(tmp_path,), process_broker=broker
    )

    result = await _run_command(tmp_path, tool, task_id="t1", source="interactive")

    assert not result.ok
    assert result.approval_id, "an unapproved run must park on approval, not run"


async def test_upstream_approval_does_not_override_process_deny(tmp_path: Path) -> None:
    from Sprout.workspace.models import Workspace, WorkspaceKind

    layer = _layer()
    broker = _broker(layer)
    result = await broker.run(
        Workspace(id="ws", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY),
        ["git", "push", "--force"],
        cwd=tmp_path,
        task_id="task-denied",
        upstream_approval_granted=True,
    )

    assert not result.allowed
    assert not result.approval_id

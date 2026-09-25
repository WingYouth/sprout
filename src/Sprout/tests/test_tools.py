"""Security layer tests: risk policy, approval workflow, gated tool execution."""

from __future__ import annotations

import pytest

from Sprout.events.bus import EventBus
from Sprout.events.types import APPROVAL_REQUESTED, TOOL_DENIED, TOOL_EXECUTED
from Sprout.security.approval import ApprovalManager, ApprovalStatus
from Sprout.security.policy import Decision, SecurityPolicy
from Sprout.security.risk import RiskLevel
from Sprout.storage.local.memory import MemoryOperationalStore
from Sprout.tests.conftest import EchoTool
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec
from Sprout.tools.system_tools import GitInspectTool, GitWriteTool


def _spec(name: str, risk: str) -> ToolSpec:
    return ToolSpec(name=name, description="test", input_schema={}, risk_level=risk)


# -- RiskLevel ---------------------------------------------------------------


def test_risk_level_severity_ordering() -> None:
    assert RiskLevel.coerce("low").severity < RiskLevel.coerce("medium").severity
    assert RiskLevel.coerce("critical").severity > RiskLevel.coerce("high").severity
    assert RiskLevel.coerce("CRITICAL") is RiskLevel.CRITICAL


# -- SecurityPolicy ----------------------------------------------------------


def test_policy_always_allow_and_deny_override_risk() -> None:
    policy = SecurityPolicy(always_allow=frozenset({"xray"}), always_deny=frozenset({"forbidden"}))
    assert policy.check(_spec("xray", "critical")) is Decision.ALLOW
    assert policy.check(_spec("forbidden", "low")) is Decision.DENY


def test_policy_risk_ladder() -> None:
    policy = SecurityPolicy()
    assert policy.check(_spec("a", "low")) is Decision.ALLOW
    assert policy.check(_spec("b", "medium")) is Decision.ALLOW
    assert policy.check(_spec("c", "high")) is Decision.REQUIRE_APPROVAL
    assert policy.check(_spec("d", "critical")) is Decision.DENY


def test_policy_medium_risk_can_require_approval() -> None:
    policy = SecurityPolicy(allow_medium_risk=False)
    assert policy.check(_spec("m", "medium")) is Decision.REQUIRE_APPROVAL


# -- ApprovalManager ---------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_lifecycle_and_single_use() -> None:
    manager = ApprovalManager(MemoryOperationalStore())

    record = await manager.request("deploy", {"env": "prod"}, task_id="task-1")
    assert record.status is ApprovalStatus.PENDING
    assert await manager.pending() == [record]
    assert not await manager.is_approved("deploy", {"env": "prod"}, task_id="task-1")

    decided = await manager.decide(record.id, True, decided_by="alice")
    assert decided.status is ApprovalStatus.APPROVED
    assert decided.decided_by == "alice"

    # One-time grant: the first use succeeds and consumes it.
    assert await manager.is_approved("deploy", {"env": "prod"}, task_id="task-1")
    assert not await manager.is_approved("deploy", {"env": "prod"}, task_id="task-1")
    assert not await manager.is_approved("deploy", {"env": "staging"}, task_id="task-1")


@pytest.mark.asyncio
async def test_memory_store_reads_do_not_mutate_persisted_approval_implicitly() -> None:
    store = MemoryOperationalStore()
    manager = ApprovalManager(store)
    record = await manager.request("deploy", {"env": "prod"}, task_id="task-1")
    record.status = ApprovalStatus.APPROVED

    assert (await store.get_approval(record.id)).status is ApprovalStatus.PENDING
    assert await manager.decide(record.id, True)
    assert (await store.get_approval(record.id)).status is ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approval_is_not_reused_across_tasks() -> None:
    manager = ApprovalManager(MemoryOperationalStore())

    record = await manager.request("deploy", {"env": "prod"}, task_id="task-1")
    await manager.decide(record.id, True)

    # Same tool and arguments under another task must not inherit the grant.
    assert not await manager.is_approved("deploy", {"env": "prod"}, task_id="task-2")
    assert await manager.is_approved("deploy", {"env": "prod"}, task_id="task-1")


@pytest.mark.asyncio
async def test_task_scoped_grant_survives_repeated_use() -> None:
    manager = ApprovalManager(MemoryOperationalStore())

    record = await manager.request(
        "git.commit", {"proposal_id": "p1"}, task_id="task-1", single_use=False
    )
    await manager.decide(record.id, True)

    assert await manager.is_approved("git.commit", {"proposal_id": "p1"}, task_id="task-1")
    assert await manager.is_approved("git.commit", {"proposal_id": "p1"}, task_id="task-1")


@pytest.mark.asyncio
async def test_expired_approval_is_not_honoured() -> None:
    manager = ApprovalManager(MemoryOperationalStore())

    record = await manager.request(
        "deploy", {"env": "prod"}, task_id="task-1", ttl_seconds=-1
    )
    await manager.decide(record.id, True)

    assert not await manager.is_approved("deploy", {"env": "prod"}, task_id="task-1")
    stored = await manager.pending()  # pending list no longer contains it
    assert record.id not in {item.id for item in stored}


@pytest.mark.asyncio
async def test_fingerprint_is_canonical() -> None:
    assert ApprovalManager.fingerprint({"b": 1, "a": 2}) == ApprovalManager.fingerprint(
        {"a": 2, "b": 1}
    )


@pytest.mark.asyncio
async def test_decide_twice_raises() -> None:
    manager = ApprovalManager(MemoryOperationalStore())
    record = await manager.request("deploy", {})
    await manager.decide(record.id, False)
    with pytest.raises(ValueError, match="already decided"):
        await manager.decide(record.id, True)


@pytest.mark.asyncio
async def test_decide_publishes_approval_decided_event() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("*", lambda event: seen.append(event.name))
    manager = ApprovalManager(MemoryOperationalStore(), events=bus)

    record = await manager.request("deploy", {"env": "prod"})
    await manager.decide(record.id, approved=True, decided_by="alice")

    assert "approval.decided" in seen


# -- ToolExecutor ------------------------------------------------------------


def _registry(*tools) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_git_tools_expose_common_inspect_and_write_operations() -> None:
    inspect_ops = set(
        GitInspectTool.spec.input_schema["properties"]["operation"]["enum"]
    )
    write_ops = set(GitWriteTool.spec.input_schema["properties"]["operation"]["enum"])

    assert {
        "status",
        "log",
        "branch",
        "diff",
        "show",
        "remote",
        "tag",
        "stash_list",
        "rev_parse",
        "ls_files",
    } <= inspect_ops
    assert {
        "add",
        "commit",
        "pull",
        "fetch",
        "push",
        "checkout",
        "switch",
        "branch_create",
        "branch_delete",
        "merge",
        "rebase",
        "reset",
        "restore",
        "revert",
        "stash_push",
        "stash_apply",
        "stash_pop",
        "stash_drop",
        "tag_create",
        "tag_delete",
        "clone",
    } <= write_ops
    assert GitInspectTool.spec.risk_level == "low"
    assert GitWriteTool.spec.risk_level == "high"


@pytest.mark.asyncio
async def test_git_inspect_diff_builds_structured_command(monkeypatch) -> None:
    calls = []

    async def fake_run_git(args):
        calls.append(args)
        return ToolResult.success("ok")

    monkeypatch.setattr("Sprout.tools.system_tools._run_git", fake_run_git)

    result = await GitInspectTool().invoke(
        {
            "operation": "diff",
            "repo": "/repo",
            "base": "main",
            "ref": "HEAD",
            "name_only": True,
            "files": ["src/app.py"],
        }
    )

    assert result.ok
    assert calls == [
        ["-C", "/repo", "diff", "--name-only", "main..HEAD", "--", "src/app.py"]
    ]


@pytest.mark.asyncio
async def test_git_write_push_and_restore_build_structured_commands(monkeypatch) -> None:
    calls = []

    async def fake_run_git(args):
        calls.append(args)
        return ToolResult.success("ok")

    monkeypatch.setattr("Sprout.tools.system_tools._run_git", fake_run_git)

    push = await GitWriteTool().invoke(
        {
            "operation": "push",
            "repo": "/repo",
            "remote": "origin",
            "branch": "feature/git-tools",
            "set_upstream": True,
        }
    )
    restore = await GitWriteTool().invoke(
        {
            "operation": "restore",
            "repo": "/repo",
            "ref": "HEAD",
            "files": ["README.md"],
        }
    )

    assert push.ok and restore.ok
    assert calls == [
        ["-C", "/repo", "push", "--set-upstream", "origin", "feature/git-tools"],
        ["-C", "/repo", "restore", "--source", "HEAD", "--", "README.md"],
    ]


@pytest.mark.asyncio
async def test_git_tools_fall_back_when_broker_lacks_new_operations(monkeypatch) -> None:
    calls = []

    async def fake_run_git(args):
        calls.append(args)
        return ToolResult.success("ok")

    monkeypatch.setattr("Sprout.tools.system_tools._run_git", fake_run_git)

    inspect = await GitInspectTool(git_broker=object()).invoke(
        {"operation": "rev_parse", "repo": "/repo", "ref": "HEAD"}
    )
    write = await GitWriteTool(git_broker=object()).invoke(
        {
            "operation": "push",
            "repo": "/repo",
            "remote": "origin",
            "branch": "main",
        }
    )

    assert inspect.ok and write.ok
    assert calls == [
        ["-C", "/repo", "rev-parse", "--verify", "HEAD"],
        ["-C", "/repo", "push", "origin", "main"],
    ]


@pytest.mark.asyncio
async def test_executor_unknown_tool_fails() -> None:
    executor = ToolExecutor(tools=ToolRegistry())
    result = await executor.execute("nope", {})
    assert not result.ok
    assert "Unknown tool" in result.to_text()


@pytest.mark.asyncio
async def test_executor_denies_critical_risk() -> None:
    events = EventBus()
    seen: list[str] = []
    events.subscribe("*", lambda event: seen.append(event.name))

    tool = EchoTool(risk_level="critical")
    executor = ToolExecutor(tools=_registry(tool), events=events)

    result = await executor.execute("echo_tool", {"text": "x"})
    assert not result.ok
    assert "denied" in result.to_text().lower()
    assert tool.seen == []  # never invoked
    assert TOOL_DENIED in seen


@pytest.mark.asyncio
async def test_executor_fails_safe_without_approval_manager() -> None:
    tool = EchoTool(risk_level="high")
    executor = ToolExecutor(tools=_registry(tool))  # no approvals wired

    result = await executor.execute("echo_tool", {"text": "x"})
    assert not result.ok
    assert tool.seen == []


@pytest.mark.asyncio
async def test_executor_requests_approval_then_runs_after_consent() -> None:
    tool = EchoTool(risk_level="high")
    approvals = ApprovalManager(MemoryOperationalStore())
    events = EventBus()
    seen: list[str] = []
    events.subscribe("*", lambda event: seen.append(event.name))
    executor = ToolExecutor(tools=_registry(tool), approvals=approvals, events=events)

    first = await executor.execute("echo_tool", {"text": "x"})
    assert not first.ok
    assert first.approval_id is not None
    assert tool.seen == []
    assert APPROVAL_REQUESTED in seen

    pending = await approvals.pending()
    assert len(pending) == 1
    await approvals.decide(pending[0].id, True)

    second = await executor.execute("echo_tool", {"text": "x"})
    assert second.ok
    assert tool.seen == [{"text": "x"}]
    assert TOOL_EXECUTED in seen


@pytest.mark.asyncio
async def test_executor_turns_tool_errors_into_failures() -> None:
    class BrokenTool:
        def __init__(self) -> None:
            self.spec = _spec("broken", "low")

        async def invoke(self, arguments):
            raise RuntimeError("boom")

    broken = BrokenTool()
    executor = ToolExecutor(tools=_registry(broken))
    result = await executor.execute("broken", {})
    assert not result.ok
    assert "RuntimeError" in result.to_text()

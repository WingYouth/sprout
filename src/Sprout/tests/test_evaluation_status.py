"""EVALUATION reports three outcomes, not two.

A verification command can be withheld by policy (it needs approval), and that
is not the same as failing. Conflating them made evaluation look like it was
working — it reported "failed" on every run while executing nothing — and it
made the verify-loop retry a condition that retrying cannot change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Sprout.orchestration.models import ExecutionNode, NodeStatus, NodeType
from Sprout.runtime.nodes import NodeExecutor, verification_status


def _evaluation(output: dict) -> ExecutionNode:
    return ExecutionNode(
        id="T:evaluation",
        task_id="T",
        type=NodeType.EVALUATION,
        status=NodeStatus.COMPLETED,
        metadata={"output": output},
    )


def _skipped(node_id: str) -> ExecutionNode:
    """What the verify-loop writes for a round it does not run."""
    return ExecutionNode(
        id=node_id,
        task_id="T",
        type=NodeType.EVALUATION,
        status=NodeStatus.SKIPPED,
        metadata={"output": {"skipped": True}},
    )


def test_output_for_skips_placeholder_outputs() -> None:
    """A skipped round must not shadow the evaluation that actually ran.

    Regression: ``_output_for`` returned the last match, which after a green
    (or unverified) first round was the skipped placeholder — so the approval
    node built change proposals from an empty node and the verification status
    never reached the approver.
    """
    real = _evaluation({"status": "not_verified", "unverified_commands": ["a"]})
    placeholder = _skipped("T:evaluation:1")

    found = NodeExecutor._output_for([real, placeholder], NodeType.EVALUATION)

    assert found == {"status": "not_verified", "unverified_commands": ["a"]}


def test_output_for_returns_none_when_only_placeholders() -> None:
    assert NodeExecutor._output_for([_skipped("T:evaluation:1")], NodeType.EVALUATION) is None


def test_output_for_still_returns_the_latest_real_output() -> None:
    """Skipping placeholders must not change which real output wins."""
    first = _evaluation({"status": "failed", "round": 1})
    second = ExecutionNode(
        id="T:evaluation:1",
        task_id="T",
        type=NodeType.EVALUATION,
        status=NodeStatus.COMPLETED,
        metadata={"output": {"status": "passed", "round": 2}},
    )

    assert NodeExecutor._output_for([first, second], NodeType.EVALUATION) == {
        "status": "passed",
        "round": 2,
    }


def test_status_is_unverified_when_every_command_was_withheld() -> None:
    """Nothing ran because policy withheld it: that is 'unverified', not failed."""
    assert verification_status(executed=1, failed=0, withheld=1) == "not_verified"


def test_status_is_failed_when_a_command_ran_and_failed() -> None:
    assert verification_status(executed=1, failed=1, withheld=0) == "failed"


def test_status_is_passed_when_everything_ran_and_passed() -> None:
    assert verification_status(executed=3, failed=0, withheld=0) == "passed"


def test_a_real_failure_outranks_a_withheld_command() -> None:
    """The change is known bad, whatever else did not get to run."""
    assert verification_status(executed=2, failed=1, withheld=1) == "failed"


def test_passes_beside_withheld_commands_are_only_partially_verified() -> None:
    """Some passing does not add up to a verified change."""
    assert verification_status(executed=2, failed=0, withheld=1) == "partially_verified"


def test_no_commands_is_its_own_state() -> None:
    assert verification_status(executed=0, failed=0, withheld=0) == "no_test_commands"


# -- TestResult: executed vs failed -------------------------------------------


def test_unexecuted_result_is_not_a_failure() -> None:
    """A withheld command must not read as "known bad" to a gate."""
    from Sprout.execution.models import TestResult

    withheld = TestResult(name="pytest", passed=False, executed=False)
    real_failure = TestResult(name="pytest", passed=False, executed=True)

    assert withheld.failed is False
    assert real_failure.failed is True


def test_test_result_round_trips_the_executed_flag() -> None:
    """Node metadata is JSON, and the apply gate reads it back.

    Regression: the flag was dropped on both serializers, so every result
    reconstructed as `executed=True` and the gate refused an unverified change
    with "Verification failed" — even though nothing had run.
    """
    from Sprout.execution.models import TestResult
    from Sprout.runtime.nodes import _test_result_from_payload, _test_result_payload

    for original in (
        TestResult(name="a", passed=True),
        TestResult(name="b", passed=False, executed=True),
        TestResult(name="c", passed=False, executed=False),
    ):
        restored = _test_result_from_payload(_test_result_payload(original))
        assert restored.executed == original.executed
        assert restored.failed == original.failed


def test_legacy_payload_defaults_to_executed() -> None:
    """Rows written before withheld commands existed always executed."""
    from Sprout.runtime.nodes import _test_result_from_payload

    assert _test_result_from_payload({"name": "old", "passed": False}).executed is True


# -- apply gate ---------------------------------------------------------------


def test_apply_gate_ignores_withheld_commands() -> None:
    """An unverified change may land once a human approved the diff.

    Regression: the gate used ``not passed``, so five withheld commands read
    as five failures and apply refused with "Verification failed" — blocking a
    change nobody had judged, after review.
    """
    from Sprout.execution.models import TestResult
    from Sprout.runtime.changes import blocking_test_failures

    withheld = [
        TestResult(name="pytest", passed=False, executed=False),
        TestResult(name="ruff check src", passed=False, executed=False),
    ]

    assert blocking_test_failures(withheld) == []


def test_apply_gate_still_blocks_real_failures() -> None:
    from Sprout.execution.models import TestResult
    from Sprout.runtime.changes import blocking_test_failures

    results = [
        TestResult(name="pytest", passed=False, executed=True),
        TestResult(name="ruff", passed=True, executed=True),
    ]

    assert blocking_test_failures(results) == ["pytest"]


def test_apply_gate_blocks_a_mix_of_failure_and_withheld() -> None:
    """A real failure still blocks, whatever else never ran."""
    from Sprout.execution.models import TestResult
    from Sprout.runtime.changes import blocking_test_failures

    results = [
        TestResult(name="pytest", passed=False, executed=True),
        TestResult(name="ruff", passed=False, executed=False),
    ]

    assert blocking_test_failures(results) == ["pytest"]


def test_apply_gate_ignores_failed_checks_for_untouched_languages() -> None:
    from Sprout.execution.models import TestResult
    from Sprout.runtime.changes import blocking_test_failures

    results = [
        TestResult(name="test: pytest src/tests/test_example.py", passed=True),
        TestResult(name="test: npm test", passed=False, output="Missing script"),
        TestResult(name="build: npm run build", passed=False, output="no package.json"),
    ]

    assert blocking_test_failures(results, ("sample_module.py",)) == []
    assert blocking_test_failures(results, ("web/frontend/App.tsx",)) == [
        "test: npm test",
        "build: npm run build",
    ]


# -- withheld commands park on an approval ------------------------------------


def test_withheld_commands_make_the_node_wait() -> None:
    """A parked command must not let the node conclude.

    ``completed`` is terminal and resume skips completed nodes, so concluding
    here would make the grant pointless: the approved command would never
    re-run and the change would land on a result that predates the approval.
    """
    from Sprout.execution.models import ProcessResult

    parked = ProcessResult(
        command=("pytest",), allowed=False, error="requires approval",
        approval_id="apr-1",
    )

    assert parked.needs_approval is True
    assert parked.approval_id == "apr-1"


def test_a_refusal_is_not_parked() -> None:
    """Withheld without a grant is a refusal, and must not park the task."""
    from Sprout.execution.models import ProcessResult

    refused = ProcessResult(command=("pytest",), allowed=False, error="denied")

    assert refused.needs_approval is False


def test_denied_decision_does_not_park() -> None:
    """Only REQUIRE_APPROVAL parks; a deny stays a plain refusal."""
    from Sprout.execution.models import ProcessResult

    denied = ProcessResult(
        command=("rm", "-rf", "/"), allowed=False, error="denied by policy"
    )

    assert denied.needs_approval is False
    assert "denied" in (denied.error or "")


# -- the broker asks instead of refusing --------------------------------------


@pytest.mark.asyncio
async def test_process_broker_raises_an_approval_request(tmp_path: Path) -> None:
    """A withheld command asks a human rather than silently failing.

    Regression: the broker returned ``allowed=False`` for every non-ALLOW
    verdict including REQUIRE_APPROVAL, so verification commands were refused
    outright and *nobody was ever asked*. Every EVALUATION round reported
    failure while executing nothing.
    """
    from Sprout.execution.process_broker import ProcessBroker
    from Sprout.security.approval import ApprovalManager
    from Sprout.security.engine import PolicyEngine
    from Sprout.storage.local.sqlite.operational import open_operational_store
    from Sprout.workspace.models import Workspace, WorkspaceKind

    operational = open_operational_store(str(tmp_path / "op.db"))
    try:
        approvals = ApprovalManager(operational)
        broker = ProcessBroker(PolicyEngine(), approvals=approvals)
        workspace = Workspace(
            id="ws", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY
        )

        result = await broker.run(
            workspace,
            ("pytest", "-q"),
            cwd=tmp_path,
            task_id="task-1",
            source="interactive",
        )

        assert not result.allowed
        # Asked, not refused.
        assert result.needs_approval
        pending = await approvals.find_pending(
            "process_run",
            {
                "action": "verification_commands",
                "task_id": "task-1",
                "resource_scope": "",
            },
            task_id="task-1",
        )
        assert pending is not None
    finally:
        operational.close()


@pytest.mark.asyncio
async def test_process_broker_without_a_manager_still_refuses(tmp_path: Path) -> None:
    """No approval manager means no one to ask: the refusal stands."""
    from Sprout.execution.process_broker import ProcessBroker
    from Sprout.security.engine import PolicyEngine
    from Sprout.workspace.models import Workspace, WorkspaceKind

    broker = ProcessBroker(PolicyEngine())
    workspace = Workspace(id="ws", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY)

    result = await broker.run(
        workspace, ("pytest", "-q"), cwd=tmp_path, task_id="t", source="interactive"
    )

    assert not result.allowed
    assert not result.needs_approval


@pytest.mark.asyncio
async def test_process_broker_refuses_for_an_unattended_source(tmp_path: Path) -> None:
    """Nobody is watching a cron run, so parking would hang the task forever."""
    from Sprout.execution.process_broker import ProcessBroker
    from Sprout.security.approval import ApprovalManager
    from Sprout.security.engine import PolicyEngine
    from Sprout.storage.local.sqlite.operational import open_operational_store
    from Sprout.workspace.models import Workspace, WorkspaceKind

    operational = open_operational_store(str(tmp_path / "op.db"))
    try:
        broker = ProcessBroker(
            PolicyEngine(), approvals=ApprovalManager(operational)
        )
        workspace = Workspace(
            id="ws", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY
        )

        result = await broker.run(
            workspace,
            ("pytest", "-q"),
            cwd=tmp_path,
            task_id="t",
            source="cron",
        )

        assert not result.allowed
        assert not result.needs_approval
        assert "unattended" in (result.error or "")
    finally:
        operational.close()

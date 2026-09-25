"""Change proposal construction."""

from __future__ import annotations

from Sprout.execution.models import (
    ChangeProposal,
    DiffResult,
    SandboxRef,
    TestResult,
)


class ChangeProposalBuilder:
    def build(
        self,
        task_id: str,
        *,
        sandbox_ref: SandboxRef | None = None,
        files_changed: tuple[str, ...] = (),
        test_results: tuple[TestResult, ...] = (),
        diffs: tuple[DiffResult, ...] = (),
        risk: str = "medium",
        required_capability_diff: tuple[str, ...] = (),
        rollback_plan: str = "",
    ) -> ChangeProposal:
        return ChangeProposal(
            task_id=task_id,
            sandbox_ref=sandbox_ref,
            files_changed=files_changed,
            test_results=test_results,
            diffs=diffs,
            risk=risk,
            required_capability_diff=required_capability_diff,
            rollback_plan=rollback_plan,
        )

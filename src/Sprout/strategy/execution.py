"""Translate a strategy plan into an executable coding task specification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from Sprout.strategy.models import StrategyPlan
from Sprout.task.models import TaskBudget

_DEFAULT_CODING_TOOLS = (
    "sandbox_read_file",
    "sandbox_list_files",
    "sandbox_search",
    "sandbox_git_inspect",
    "sandbox_write_file",
    "sandbox_delete_file",
    "sandbox_edit_file",
    "sandbox_apply_patch",
)

#: Upper bound on automatically-read resources for one task. The agent can
#: still read anything else through ``sandbox_read_file``/``sandbox_search``;
#: this only bounds what the runtime pre-loads into every node's context.
_MAX_TASK_RESOURCES = 40


def _capped_paths(paths: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    """Deduplicate ``paths``, preserving order, and keep at most ``limit``."""
    return tuple(dict.fromkeys(paths))[:limit]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Everything the execution layer needs to run one coding task."""

    instruction: str
    resources: tuple[str, ...] = ()
    tools: tuple[str, ...] = _DEFAULT_CODING_TOOLS
    budget: TaskBudget = field(default_factory=TaskBudget)
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionPlanner:
    """Turn a :class:`StrategyPlan` into a concrete :class:`TaskSpec`."""

    def plan_to_task_spec(self, plan: StrategyPlan) -> TaskSpec:
        # Cap the automatic reads, strongest evidence first. The raw report
        # lists every source file at baseline confidence, and
        # ``build_read_plan`` stats and reads each one — a real project turned
        # that into 1030 required paths and 438 resources spanning ~2s of I/O.
        #
        # Order matters as much as the bound: concatenating the category
        # buckets put ~100 "interface" files first purely because their paths
        # sort early, so the capped list was forty gateway files and none of
        # the file the requirement named. Ranking by match puts the relevant
        # ones inside the cut.
        resources = _capped_paths(
            (*plan.impact.top_paths(_MAX_TASK_RESOURCES), *plan.test_files),
            limit=_MAX_TASK_RESOURCES,
        )
        return TaskSpec(
            instruction=self._instruction(plan),
            resources=resources,
            tools=_DEFAULT_CODING_TOOLS,
            budget=TaskBudget(
                max_model_calls=12,
                max_tool_calls=30,
                max_tokens=120_000,
            ),
            metadata={
                "mode": plan.mode.value,
                "strategy": plan.to_dict(),
                "test_files": list(plan.test_files),
                "risks": list(plan.risks),
                # Structured decomposition as plain data, so the graph compiler
                # can build per-step nodes without importing the strategy layer.
                "steps": [
                    {
                        "description": step.description,
                        "kind": step.kind.value,
                        "target_paths": list(step.target_paths),
                        "acceptance": step.acceptance,
                    }
                    for step in plan.steps
                ],
                # The acceptance criteria as runnable commands, so the
                # EVALUATION node verifies against what the requirement needs
                # rather than only the workspace's generic test command. These
                # were previously rendered into the instruction text and never
                # executed: the agent was told to satisfy `ruff check src` while
                # verification ran `npm test`.
                "verification_commands": [
                    {
                        "kind": item.kind.value,
                        "name": item.name,
                        "command": item.command,
                        "expected": item.expected,
                        "required": item.required,
                    }
                    for item in plan.verification.criteria
                ],
            },
        )

    @staticmethod
    def _instruction(plan: StrategyPlan) -> str:
        lines = [
            f"Implement this requirement in the project: {plan.requirement.text}",
            f"Change mode: {plan.mode.value}",
        ]
        if plan.implementation_steps:
            lines.append("Implementation steps:")
            lines.extend(f"- {step}" for step in plan.implementation_steps)
        if plan.test_files:
            lines.append("Test files to add or update:")
            lines.extend(f"- {path}" for path in plan.test_files)
        if plan.verification.criteria:
            lines.append("Verification criteria:")
            lines.extend(
                f"- {item.kind.value}/{item.name}: {item.command} "
                f"(expect {item.expected})"
                for item in plan.verification.criteria
            )
        if plan.risks:
            lines.append("Risks and notes:")
            lines.extend(f"- {risk}" for risk in plan.risks)
        return "\n".join(lines)

"""Build a deterministic V0.1 execution graph from a task and read plan."""

from __future__ import annotations

from collections.abc import Mapping

from Sprout.orchestration.models import (
    ExecutionGraph,
    ExecutionNode,
    NodeBudget,
    NodeType,
)
from Sprout.task.models import Task
from Sprout.workspace.models import ReadPlan, WorkspaceManifest


class ExecutionGraphBuilder:
    """Compiles the initial sequential project task shape."""

    def build(
        self,
        task: Task,
        read_plan: ReadPlan,
        manifest: WorkspaceManifest,
        *,
        verify_loops: int = 1,
        agent_max_attempts: int = 2,
        agent_timeout_seconds: float = 300.0,
        evaluation_timeout_seconds: float = 600.0,
        evaluation_attempts: int = 2,
        agent_tool_names: tuple[str, ...] = (),
        steps: tuple[Mapping[str, object], ...] = (),
        verification_commands: tuple[Mapping[str, object], ...] = (),
    ) -> ExecutionGraph:
        read_id = f"{task.id}:read"
        sandbox_id = f"{task.id}:sandbox"
        plan_id = f"{task.id}:plan"
        approval_id = f"{task.id}:approval"
        apply_id = f"{task.id}:apply"

        read_node = ExecutionNode(
            id=read_id,
            task_id=task.id,
            type=NodeType.READ,
            metadata={
                "read_plan_id": read_plan.id,
                "purpose": read_plan.purpose,
                "resources": [ref.path for ref in read_plan.resources],
            },
        )
        sandbox_node = ExecutionNode(
            id=sandbox_id,
            task_id=task.id,
            type=NodeType.SANDBOX,
            dependencies=(read_id,),
        )
        plan_node = ExecutionNode(
            id=plan_id,
            task_id=task.id,
            type=NodeType.PLAN,
            dependencies=(sandbox_id,),
            metadata={"instruction": task.instruction},
            budget=NodeBudget(
                max_attempts=agent_max_attempts,
                timeout_seconds=agent_timeout_seconds,
            ),
        )

        # Each plan step becomes a read-only SUBTASK node. Every one of them is
        # read-only regardless of its ``kind`` — the tool set is
        # read/list/search/git-inspect, and the write tools exist only on the
        # AGENT nodes — so their independence (each depends only on PLAN, never
        # on a sibling) is a concurrency opportunity for the whole set, not
        # just the steps the model labelled ANALYSIS. The first edit round
        # waits for all of them, which is what makes their evidence available
        # to the agent.
        #
        # They are also emitted *after* PLAN and before every AGENT in
        # declaration order. The Temporal workflow runs nodes positionally and
        # never reads ``dependencies``, so this ordering is what keeps it
        # correct there; do not reorder these without updating that workflow.
        subtask_nodes, subtask_ids = self._subtask_nodes(
            task, plan_id, steps, agent_timeout_seconds
        )

        # ``verify_loops`` turns the single AGENT -> EVALUATION pair into a
        # bounded edit-test-fix loop. Every later agent sees the previous
        # evaluation output and can repair a failing change before approval.
        loops = max(1, verify_loops)
        nodes: list[ExecutionNode] = [read_node, sandbox_node, plan_node, *subtask_nodes]
        previous_evaluation_id: str | None = None
        for index in range(loops):
            agent_id = f"{task.id}:agent" if index == 0 else f"{task.id}:agent:{index}"
            verify_id = (
                f"{task.id}:evaluation"
                if index == 0
                else f"{task.id}:evaluation:{index}"
            )
            agent_metadata: dict[str, object] = {"instruction": task.instruction}
            if previous_evaluation_id is not None:
                agent_metadata["previous_evaluation_node_id"] = previous_evaluation_id
            if agent_tool_names:
                agent_metadata["tool_names"] = list(agent_tool_names)
            # The first edit round waits for every subtask's evidence (each of
            # which already depends on PLAN); later rounds chain off the
            # previous evaluation so they can repair a failed change instead.
            if previous_evaluation_id is not None:
                agent_dependencies: tuple[str, ...] = (previous_evaluation_id,)
            elif subtask_ids:
                agent_dependencies = subtask_ids
            else:
                agent_dependencies = (plan_id,)
            agent_node = ExecutionNode(
                id=agent_id,
                task_id=task.id,
                type=NodeType.AGENT,
                dependencies=agent_dependencies,
                metadata=agent_metadata,
                budget=NodeBudget(
                    max_attempts=agent_max_attempts,
                    timeout_seconds=agent_timeout_seconds,
                ),
            )
            verify_node = ExecutionNode(
                id=verify_id,
                task_id=task.id,
                type=NodeType.EVALUATION,
                dependencies=(agent_id,),
                metadata={
                    "test_commands": list(manifest.test_commands),
                    "build_commands": list(manifest.build_commands),
                    "verification_attempts": evaluation_attempts,
                    # Requirement-specific acceptance commands from the
                    # strategy layer. They run in addition to the manifest's
                    # generic ones: the manifest says "this project has tests",
                    # strategy says "this change must satisfy these".
                    "verification_commands": [
                        {
                            "kind": str(item.get("kind") or "code"),
                            "name": str(item.get("name") or ""),
                            "command": str(item.get("command") or ""),
                            "expected": str(item.get("expected") or ""),
                            "required": bool(item.get("required", True)),
                        }
                        for item in verification_commands
                        if isinstance(item, Mapping) and item.get("command")
                    ],
                },
                budget=NodeBudget(
                    max_attempts=1,
                    timeout_seconds=evaluation_timeout_seconds,
                ),
            )
            nodes.extend((agent_node, verify_node))
            previous_evaluation_id = verify_id

        approval_node = ExecutionNode(
            id=approval_id,
            task_id=task.id,
            type=NodeType.APPROVAL,
            dependencies=(previous_evaluation_id or "",),
        )
        apply_node = ExecutionNode(
            id=apply_id,
            task_id=task.id,
            type=NodeType.APPLY,
            dependencies=(approval_id,),
        )
        return ExecutionGraph(
            task_id=task.id,
            nodes=tuple(nodes) + (approval_node, apply_node),
            entry_node_ids=(read_id,),
        )

    @staticmethod
    def _subtask_nodes(
        task: Task,
        plan_id: str,
        steps: tuple[Mapping[str, object], ...],
        timeout_seconds: float,
    ) -> tuple[list[ExecutionNode], tuple[str, ...]]:
        """Compile plan steps into read-only SUBTASK nodes.

        Malformed steps are skipped rather than rejected: the steps travel as
        plain data from task metadata, and one bad entry must not cost the whole
        graph. A task with no usable steps yields no subtasks, leaving the graph
        exactly as it was before decomposition existed.
        """
        nodes: list[ExecutionNode] = []
        ids: list[str] = []
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            description = str(step.get("description") or "").strip()
            if not description:
                continue
            node_id = f"{task.id}:subtask:{index}"
            ids.append(node_id)
            nodes.append(
                ExecutionNode(
                    id=node_id,
                    task_id=task.id,
                    type=NodeType.SUBTASK,
                    dependencies=(plan_id,),
                    metadata={
                        "index": index,
                        "description": description,
                        "kind": str(step.get("kind") or "other"),
                        "target_paths": [
                            str(path) for path in step.get("target_paths") or ()
                        ],
                        "acceptance": str(step.get("acceptance") or ""),
                    },
                    budget=NodeBudget(
                        max_attempts=1,
                        timeout_seconds=timeout_seconds,
                    ),
                )
            )
        return nodes, tuple(ids)

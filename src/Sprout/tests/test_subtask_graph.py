"""PLAN -> SUBTASK -> AGENT decomposition.

A strategy plan's structured steps compile into read-only SUBTASK nodes that
sit between PLAN and the first edit round. They all depend only on PLAN, so
the scheduler may run the analysis ones concurrently, and the first AGENT
waits for every one of them so their evidence reaches the prompt.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.orchestration.compiler import ExecutionGraphBuilder
from Sprout.orchestration.models import NodeType
from Sprout.runtime.nodes import NodeExecutor
from Sprout.task.models import Task
from Sprout.workspace.models import ReadPlan, Workspace, WorkspaceKind, WorkspaceManifest

STEPS = (
    {"description": "读现有实现", "kind": "analysis", "target_paths": ["src/a.py"]},
    {"description": "改代码", "kind": "edit", "target_paths": ["src/a.py"]},
)


def _graph(steps=()):
    task = Task(id="T", workspace_id="ws", instruction="do it")
    return ExecutionGraphBuilder().build(
        task,
        ReadPlan(purpose="p"),
        WorkspaceManifest(workspace_id="ws"),
        verify_loops=2,
        steps=steps,
    )


def test_no_steps_leaves_the_graph_shape_unchanged() -> None:
    """The default path must not grow subtasks or change dependencies."""
    graph = _graph()

    assert [node.type.value for node in graph.nodes] == [
        "read", "sandbox", "plan", "agent", "evaluation",
        "agent", "evaluation", "approval", "apply",
    ]
    assert [node for node in graph.nodes if node.type is NodeType.SUBTASK] == []


def test_steps_become_independent_subtask_nodes() -> None:
    graph = _graph(STEPS)
    subtasks = [node for node in graph.nodes if node.type is NodeType.SUBTASK]

    assert len(subtasks) == len(STEPS)
    # Independent by design: this is what lets the scheduler parallelise them.
    for node in subtasks:
        assert node.dependencies == ("T:plan",)
    assert [node.metadata["description"] for node in subtasks] == [
        "读现有实现",
        "改代码",
    ]
    assert subtasks[0].metadata["kind"] == "analysis"
    assert subtasks[0].metadata["target_paths"] == ["src/a.py"]


def test_first_agent_waits_for_every_subtask() -> None:
    graph = _graph(STEPS)
    agents = [node for node in graph.nodes if node.type is NodeType.AGENT]

    assert agents[0].dependencies == ("T:subtask:0", "T:subtask:1")
    # Later rounds still chain off the previous evaluation.
    assert agents[1].dependencies == ("T:evaluation",)


def test_subtasks_precede_agents_in_declaration_order() -> None:
    """The Temporal workflow runs nodes positionally and ignores dependencies.

    It therefore relies on SUBTASK nodes being declared before every AGENT.
    Tying the invariant to a test keeps a future reorder from silently making
    the Temporal path run the edit round before its investigation.
    """
    graph = _graph(STEPS)
    types = [node.type for node in graph.nodes]

    last_subtask = max(i for i, t in enumerate(types) if t is NodeType.SUBTASK)
    first_agent = min(i for i, t in enumerate(types) if t is NodeType.AGENT)
    first_plan = min(i for i, t in enumerate(types) if t is NodeType.PLAN)

    assert first_plan < last_subtask < first_agent


def test_temporal_codec_round_trips_subtasks() -> None:
    """The wire format must survive encoding, since Temporal sends it as JSON."""
    from Sprout.orchestration.temporal_codec import graph_to_dict, node_from_dict

    graph = _graph(STEPS)
    encoded = graph_to_dict(graph)
    decoded = [node_from_dict(node) for node in encoded["nodes"]]

    assert [node.type for node in decoded] == [node.type for node in graph.nodes]
    assert [tuple(node.dependencies) for node in decoded] == [
        tuple(node.dependencies) for node in graph.nodes
    ]


def test_malformed_steps_are_skipped_not_fatal() -> None:
    """Steps arrive as plain data from task metadata; one bad entry is survivable."""
    graph = _graph(
        (
            {"description": "  "},          # blank description
            "not-a-mapping",               # wrong type
            {"kind": "edit"},              # missing description
            {"description": "keep me", "kind": "edit"},
        )
    )
    subtasks = [node for node in graph.nodes if node.type is NodeType.SUBTASK]

    assert len(subtasks) == 1
    assert subtasks[0].metadata["description"] == "keep me"
    # Indices are positional, so the surviving node keeps its original slot.
    assert subtasks[0].id == "T:subtask:3"


def test_subtask_findings_reach_the_agent_prompt() -> None:
    from Sprout.orchestration.models import ExecutionNode, NodeStatus

    def done(index: int, kind: str, description: str, findings: str):
        return ExecutionNode(
            id=f"T:subtask:{index}",
            task_id="T",
            type=NodeType.SUBTASK,
            status=NodeStatus.COMPLETED,
            metadata={
                "index": index,
                "kind": kind,
                "description": description,
                "output": {
                    "index": index,
                    "kind": kind,
                    "description": description,
                    "findings": findings,
                },
            },
        )

    nodes = [
        done(1, "test", "补测试", "没有 test_user.py"),
        done(0, "analysis", "读实现", "只有 list_users()"),
    ]
    findings = NodeExecutor._subtask_findings(nodes)

    assert [item["index"] for item in findings] == [0, 1]  # step order

    task = Task(id="T", workspace_id="ws", instruction="加导出 CSV")
    workspace = Workspace(id="ws", root=Path("."), kind=WorkspaceKind.LOCAL_DIRECTORY)
    prompt = NodeExecutor._agent_prompt(task, workspace, (), None, "", findings)

    assert "只有 list_users()" in prompt
    assert "没有 test_user.py" in prompt
    # No findings -> no empty section.
    assert "Findings from the plan" not in NodeExecutor._agent_prompt(
        task, workspace, ()
    )


def test_subtask_findings_ignore_incomplete_nodes() -> None:
    from Sprout.orchestration.models import ExecutionNode, NodeStatus

    pending = ExecutionNode(id="T:subtask:0", task_id="T", type=NodeType.SUBTASK)
    empty = ExecutionNode(
        id="T:subtask:1",
        task_id="T",
        type=NodeType.SUBTASK,
        status=NodeStatus.COMPLETED,
        metadata={"output": {"index": 1, "kind": "other", "findings": ""}},
    )

    assert NodeExecutor._subtask_findings([pending, empty]) == ()

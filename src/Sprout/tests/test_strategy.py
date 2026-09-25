from pathlib import Path

import pytest

from Sprout.llm.messages import LLMResponse
from Sprout.strategy import ChangeMode, ImpactAnalyzer, StrategyPipeline
from Sprout.strategy.execution import ExecutionPlanner, TaskSpec
from Sprout.strategy.intake import RequirementIntake
from Sprout.strategy.models import Requirement, VerificationKind
from Sprout.task.models import Task
from Sprout.workspace.models import Workspace, WorkspaceKind
from Sprout.workspace.scanner import WorkspaceScanner


class StrategyModel:
    name = "test-model"
    model = "test-model"

    async def chat(self, messages, *, tools=()):
        return LLMResponse(
            content=(
                '{"mode":"add","strategy":"先新增编码能力接口，再补测试。",'
                '"steps":["新增接口","补充测试"],'
                '"test_files":["src/Sprout/tests/test_coding.py"],'
                '"risks":["需要审批"]}'
            )
        )


def test_strategy_pipeline_finds_surfaces_and_builds_verification_plan(tmp_path: Path) -> None:
    (tmp_path / "src/api.py").parent.mkdir(parents=True)
    (tmp_path / "src/api.py").write_text("def create_user(): pass\n", encoding="utf-8")
    (tmp_path / "src/database.py").write_text("schema = {}\n", encoding="utf-8")
    (tmp_path / "tests/test_api.py").parent.mkdir(parents=True)
    (tmp_path / "tests/test_api.py").write_text("def test_api(): pass\n", encoding="utf-8")

    plan = StrategyPipeline().plan_user_request(tmp_path, "增加用户 API 和数据库字段")

    assert plan.mode is ChangeMode.MODIFY
    assert "src/api.py" in plan.impact.interfaces
    assert "src/database.py" in plan.impact.databases
    assert "tests/test_api.py" in plan.impact.tests
    assert plan.verification.for_kind(VerificationKind.API)
    assert plan.verification.for_kind(VerificationKind.DATABASE)
    assert plan.verification.for_kind(VerificationKind.CODE)
    assert plan.to_dict()["mode"] == "modify"


def test_intake_rejects_empty_requirement() -> None:
    try:
        RequirementIntake().from_user("  ")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("empty requirements must be rejected")


@pytest.mark.asyncio
async def test_strategy_pipeline_asks_model_to_choose_strategy(tmp_path: Path) -> None:
    plan = await StrategyPipeline().plan_user_request_with_model(
        tmp_path,
        "我需要新增加一个敲代码的功能",
        StrategyModel(),
    )

    assert plan.mode is ChangeMode.ADD
    assert plan.model_name == "test-model"
    assert "新增编码能力接口" in plan.model_strategy
    assert plan.test_files == ("src/Sprout/tests/test_coding.py",)


def test_execution_planner_builds_a_coding_task_spec(tmp_path: Path) -> None:
    (tmp_path / "src/api.py").parent.mkdir(parents=True)
    (tmp_path / "src/api.py").write_text("def api(): pass\n", encoding="utf-8")

    plan = StrategyPipeline().plan_user_request(tmp_path, "新增 API")
    spec = ExecutionPlanner().plan_to_task_spec(plan)

    assert isinstance(spec, TaskSpec)
    assert "新增 API" in spec.instruction
    assert "src/api.py" in spec.resources
    assert "sandbox_apply_patch" in spec.tools
    assert "sandbox_delete_file" in spec.tools
    assert spec.budget.max_model_calls > 0
    assert spec.budget.max_tool_calls > 0
    assert spec.metadata["mode"] == plan.mode.value


def test_scanner_read_plan_includes_required_paths(tmp_path: Path) -> None:
    (tmp_path / "src/target.py").parent.mkdir(parents=True)
    (tmp_path / "src/target.py").write_text("def target(): pass\n", encoding="utf-8")
    (tmp_path / "src/other.py").write_text("def other(): pass\n", encoding="utf-8")

    workspace = Workspace(
        id="ws",
        root=tmp_path,
        kind=WorkspaceKind.LOCAL_DIRECTORY,
    )
    task = Task(id="task-1", workspace_id="ws", instruction="change target")
    plan = WorkspaceScanner().build_read_plan(
        workspace,
        task,
        required_paths=("src/target.py",),
    )

    paths = [resource.path for resource in plan.resources]
    assert any(path.endswith("src/target.py") for path in paths)


# -- structured decomposition (PlanStep) --------------------------------------


def test_model_planner_parses_structured_steps() -> None:
    """The structured shape becomes PlanStep, with kind and target paths."""
    from Sprout.strategy.model_planner import ModelStrategyPlanner
    from Sprout.strategy.models import StepKind

    steps = ModelStrategyPlanner._steps(
        [
            {
                "description": "读现有实现",
                "kind": "analysis",
                "target_paths": ["src/user.py"],
                "acceptance": "列出改动点",
            },
            {"description": "改代码", "kind": "edit", "target_paths": ["src/user.py"]},
        ]
    )

    assert [step.kind for step in steps] == [StepKind.ANALYSIS, StepKind.EDIT]
    assert steps[0].target_paths == ("src/user.py",)
    assert steps[0].acceptance == "列出改动点"
    # Reports the model's stated intent only; it is not a capability claim.
    assert steps[0].is_investigation is True
    assert steps[1].is_investigation is False


def test_model_planner_accepts_legacy_string_steps() -> None:
    """A plain string array (the pre-PlanStep shape) still parses."""
    from Sprout.strategy.model_planner import ModelStrategyPlanner
    from Sprout.strategy.models import StepKind

    steps = ModelStrategyPlanner._steps(["新增接口", "补充测试"])

    assert [step.description for step in steps] == ["新增接口", "补充测试"]
    assert all(step.kind is StepKind.OTHER for step in steps)
    assert all(step.target_paths == () for step in steps)


def test_model_planner_tolerates_malformed_steps() -> None:
    """Garbage entries are skipped, never raised on."""
    from Sprout.strategy.model_planner import ModelStrategyPlanner
    from Sprout.strategy.models import StepKind

    steps = ModelStrategyPlanner._steps(
        [{"description": "   "}, "ok", 42, None, {"description": "k", "kind": "bogus"}]
    )

    assert [step.description for step in steps] == ["ok", "k"]
    assert steps[1].kind is StepKind.OTHER  # unknown kind degrades, not raises
    assert ModelStrategyPlanner._steps("not-a-list") == ()


def test_execution_planner_caps_required_resources(tmp_path: Path) -> None:
    """A scan-heavy project must not turn into hundreds of automatic reads."""
    from Sprout.strategy.execution import _MAX_TASK_RESOURCES

    for index in range(_MAX_TASK_RESOURCES * 2):
        target = tmp_path / "src" / f"mod_{index}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def f():\n    pass\n", encoding="utf-8")

    plan = StrategyPipeline().plan_user_request(tmp_path, "改 api")
    spec = ExecutionPlanner().plan_to_task_spec(plan)

    assert len(spec.resources) <= _MAX_TASK_RESOURCES
    assert len(spec.resources) == len(set(spec.resources))  # deduplicated


def test_task_spec_carries_structured_steps() -> None:
    """Steps reach the task spec as plain data for the graph compiler."""
    from Sprout.strategy.models import (
        ChangeMode,
        ImpactReport,
        PlanStep,
        Requirement,
        StepKind,
        StrategyPlan,
        VerificationPlan,
    )

    plan = StrategyPlan(
        Requirement("加导出"),
        ChangeMode.ADD,
        ImpactReport(),
        VerificationPlan(),
        steps=(
            PlanStep("读代码", StepKind.ANALYSIS, ("src/a.py",), "列出改动点"),
            PlanStep("写代码", StepKind.EDIT, ("src/a.py",)),
        ),
    )

    spec = ExecutionPlanner().plan_to_task_spec(plan)

    assert spec.metadata["steps"] == [
        {
            "description": "读代码",
            "kind": "analysis",
            "target_paths": ["src/a.py"],
            "acceptance": "列出改动点",
        },
        {
            "description": "写代码",
            "kind": "edit",
            "target_paths": ["src/a.py"],
            "acceptance": "",
        },
    ]


# -- impact relevance ---------------------------------------------------------


def _scattered_repo(tmp_path: Path) -> None:
    """A repo shaped like a real one: a cache, many tests, a named target."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "billing.py").write_text("def charge():\n    pass\n", encoding="utf-8")
    (tmp_path / "src" / "unrelated.py").write_text("def other():\n    pass\n", encoding="utf-8")

    (tmp_path / "tests").mkdir()
    for name in ("test_alpha", "test_beta", "test_billing"):
        target = tmp_path / "tests" / f"{name}.py"
        target.write_text("def test_x():\n    pass\n", encoding="utf-8")

    # A cache directory carrying the standard marker (bford.info/cachedir).
    cache = tmp_path / ".uv-cache" / "archive"
    cache.mkdir(parents=True)
    (tmp_path / ".uv-cache" / "CACHEDIR.TAG").write_text(
        "Signature: 8a477f597d28d172789f06886806bc55\n", encoding="utf-8"
    )
    (cache / "vendor_billing.py").write_text("billing = 1\n", encoding="utf-8")

    # A cache-shaped directory with no marker: the name list must catch it.
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "cached_billing.py").write_text("x = 1\n", encoding="utf-8")


def test_impact_skips_cache_directories(tmp_path: Path) -> None:
    """Cached and vendored trees are not project source.

    Regression: an unmarked dependency cache was 61% of every impact item on
    this repository (664 of 1097 files), and its paths sorted ahead of src/.
    """
    _scattered_repo(tmp_path)
    report = ImpactAnalyzer().analyze(tmp_path, Requirement("billing change"))
    paths = [item.path for item in report.items]

    assert not [p for p in paths if p.startswith(".uv-cache/")]
    assert not [p for p in paths if p.startswith(".pytest_cache/")]
    assert "src/billing.py" in paths


def test_impact_tests_are_requirement_matched_only(tmp_path: Path) -> None:
    """An impact report must not nominate every test in the repository.

    Regression: all three test files were reported as "tests to update"
    (73 on this repo) regardless of whether the requirement touched them.
    """
    _scattered_repo(tmp_path)
    report = ImpactAnalyzer().analyze(tmp_path, Requirement("billing change"))

    assert report.tests == ("tests/test_billing.py",)


def test_impact_ranks_matched_files_first(tmp_path: Path) -> None:
    """A bounded resource list must cut noise, not relevance."""
    _scattered_repo(tmp_path)
    report = ImpactAnalyzer().analyze(tmp_path, Requirement("billing change"))

    ranked = [item.path for item in report.ranked_items()]

    assert ranked[0] == "src/billing.py"
    assert all(item.matched for item in report.top_items(1))


def test_unmatched_requirement_yields_no_test_files(tmp_path: Path) -> None:
    """No keyword match -> no test claims, so the caller proposes a new one."""
    _scattered_repo(tmp_path)
    report = ImpactAnalyzer().analyze(tmp_path, Requirement("增加导出功能"))

    assert report.tests == ()
    assert not any(item.matched for item in report.items)

"""Interactive smoke test for the requirement strategy pipeline.

Run with::

    uv run python -m Sprout.tests.interactive_test

This module is intentionally separate from pytest so automated test runs never
wait for terminal input.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from Sprout.config.loader import load_settings
from Sprout.runtime.factory import create_model_registry
from Sprout.strategy.pipeline import StrategyPipeline


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _print_plan(plan) -> None:
    report = plan.impact
    print("\n=== 需求分析报告 ===")
    print(f"需求: {plan.requirement.text}")
    print(f"来源: {plan.requirement.source.value}")
    print(f"变更判断: {plan.mode.value}")
    print("\n影响面证据:")
    print(f"接口证据: {len(report.interfaces)} 个")
    for path in report.interfaces:
        print(f"  - {path}")
    if not report.interfaces:
        print("  - 未找到匹配的接口文件，需要人工确认新增位置")
    print(f"数据库证据: {len(report.databases)} 个")
    for path in report.databases:
        print(f"  - {path}")
    if not report.databases:
        print("  - 未找到匹配的数据库文件")
    print(f"代码证据: {len(report.related_code)} 个")
    for path in report.related_code:
        print(f"  - {path}")
    if not report.related_code:
        print("  - 未找到额外的代码文件")
    print(f"测试证据: {len(report.tests)} 个")
    for path in report.tests:
        print(f"  - {path}")
    if not report.tests:
        print("  - 未找到现有测试文件，将创建测试文件")

    print("\n报告结论:")
    print(f"  共发现 {len(report.items)} 个项目证据")
    print(f"  建议变更方式: {plan.mode.value}")
    print(f"  建议测试文件: {', '.join(plan.test_files)}")
    print(f"  使用模型: {plan.model_name or '未记录'}")
    print(f"  模型战略: {plan.model_strategy or '模型未返回战略说明'}")
    print(f"  分析路径: {report.source.value}")
    if report.conflicts:
        print(f"  待交叉验证证据: {len(report.conflicts)} 个")

    print("\n验收标准:")
    for criterion in plan.verification.criteria:
        print(f"  [{criterion.kind.value}] {criterion.name}: {criterion.command}")
        print(f"      预期: {criterion.expected}")

    print("\n实施步骤:")
    for index, step in enumerate(plan.implementation_steps, start=1):
        print(f"  {index}. {step}")


def main() -> int:
    print("Sprout Strategy 交互式测试")
    print("此测试只读取项目并生成策略，不会修改文件。")
    first_input = _ask("请输入需求或项目路径")
    if not first_input:
        print("需求描述不能为空。")
        return 2

    candidate = Path(first_input).expanduser()
    if candidate.is_dir():
        root = candidate.resolve()
        requirement = _ask("需求描述")
    else:
        root = _default_project_root()
        requirement = first_input

    if not requirement:
        print("需求描述不能为空。")
        return 2

    try:
        settings = load_settings()
        model = create_model_registry(settings.model).default()
        plan = asyncio.run(
            StrategyPipeline().plan_user_request_with_model(root, requirement, model)
        )
    except Exception as exc:  # Keep the interactive diagnostic readable.
        print(f"自然语言模型战略分析失败: {exc}")
        print("已停止，未将本地规则结果伪装成模型战略。")
        return 1

    _print_plan(plan)
    print("\n报告已生成。接下来可以导出 JSON，或确认后进入审批阶段。")
    export = _ask("是否导出 JSON 计划？(y/N)", "N").casefold()
    if export in {"y", "yes", "是"}:
        output = Path(_ask("输出文件", "strategy-plan.json")).expanduser()
        output.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已导出: {output.resolve()}")

    proceed = _ask("是否确认这份策略可以进入审批与编码阶段？(y/N)", "N")
    if proceed.casefold() in {"y", "yes", "是"}:
        print("已确认。下一阶段应交给审批服务，再调用 coder/apply_patch。")
    else:
        print("已停止在只读策略阶段，项目没有被修改。")
    return 0


def _default_project_root() -> Path:
    """Resolve the repository even when the script is launched from an IDE."""
    current = Path.cwd().resolve()
    if (current / "pyproject.toml").exists() or (current / ".git").exists():
        return current
    return Path(__file__).resolve().parents[3]


if __name__ == "__main__":
    raise SystemExit(main())

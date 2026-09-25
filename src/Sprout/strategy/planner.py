"""Choose change mode and produce an implementation plan."""

from __future__ import annotations

from Sprout.strategy.models import (
    ChangeMode,
    ImpactReport,
    Requirement,
    StrategyPlan,
    VerificationPlan,
)


class RequirementPlanner:
    def build(
        self,
        requirement: Requirement,
        impact: ImpactReport,
        verification: VerificationPlan,
    ) -> StrategyPlan:
        has_existing = bool(impact.related_code or impact.interfaces or impact.databases)
        if has_existing and not impact.tests:
            mode = ChangeMode.MIXED
        elif has_existing:
            mode = ChangeMode.MODIFY
        else:
            mode = ChangeMode.ADD
        test_files = impact.tests or (self._default_test_path(requirement),)
        steps = (
            "确认影响面证据与需求边界",
            f"按 {mode.value} 策略设计接口、数据库和代码变更",
            "先补充或更新检验标准对应的测试文件",
            "通过审批后调用 coder/apply_patch 写入代码",
            "按数据库、接口、代码三个维度执行验证",
            "验证通过后创建 ChangeProposal 并记录 Git 变更",
        )
        risks = ("影响面不足或没有匹配到现有代码时，必须人工确认新增边界",)
        return StrategyPlan(requirement, mode, impact, verification, steps, test_files, risks)

    @staticmethod
    def _default_test_path(requirement: Requirement) -> str:
        slug = "_".join(requirement.text.casefold().split())[:48]
        return f"src/Sprout/tests/test_strategy_{slug or 'requirement'}.py"

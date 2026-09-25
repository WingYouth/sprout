"""High-level, read-only requirement strategy pipeline."""

from __future__ import annotations

from pathlib import Path

from Sprout.strategy.impact import ImpactAnalyzer
from Sprout.strategy.intake import RequirementIntake
from Sprout.strategy.model_planner import ModelStrategyPlanner
from Sprout.strategy.models import Requirement, StrategyPlan
from Sprout.strategy.planner import RequirementPlanner
from Sprout.strategy.verification import VerificationPlanner


class StrategyPipeline:
    """Compose intake, impact analysis, planning, and verification planning.

    Mutation is intentionally outside this class. The caller hands the plan to
    the existing approval/change service, then execution brokers perform patch,
    test, and Git operations in their own security boundaries.
    """

    def __init__(
        self,
        *,
        intake: RequirementIntake | None = None,
        impact: ImpactAnalyzer | None = None,
        planner: RequirementPlanner | None = None,
        verification: VerificationPlanner | None = None,
        model_planner: ModelStrategyPlanner | None = None,
    ) -> None:
        self.intake = intake or RequirementIntake()
        self.impact = impact or ImpactAnalyzer()
        self.planner = planner or RequirementPlanner()
        self.verification = verification or VerificationPlanner()
        self.model_planner = model_planner or ModelStrategyPlanner()

    def plan(self, root: str | Path, requirement: Requirement) -> StrategyPlan:
        report = self.impact.analyze(root, requirement)
        verification = self.verification.build(report)
        return self.planner.build(requirement, report, verification)

    def plan_user_request(
        self,
        root: str | Path,
        text: str,
        *,
        language: str = "",
    ) -> StrategyPlan:
        return self.plan(root, self.intake.from_user(text, language=language))

    def plan_scan_suggestion(self, root: str | Path, text: str) -> StrategyPlan:
        return self.plan(root, self.intake.from_scan(text))

    async def plan_user_request_with_model(
        self,
        root: str | Path,
        text: str,
        model,
        *,
        language: str = "",
    ) -> StrategyPlan:
        """Create evidence locally, then let the configured LLM choose strategy."""
        plan = self.plan_user_request(root, text, language=language)
        return await self.model_planner.refine(plan, model)

    async def plan_from_project_database(self, root, text, search, model) -> StrategyPlan:
        requirement = self.intake.from_user(text)
        report = await self.impact.analyze_from_project_database(requirement, search)
        plan = self.planner.build(requirement, report, self.verification.build(report))
        return await self.model_planner.refine(plan, model)

    async def plan_cross_validated(self, root, text, search, model) -> StrategyPlan:
        requirement = self.intake.from_user(text)
        report = await self.impact.analyze_cross_validated(root, requirement, search)
        plan = self.planner.build(requirement, report, self.verification.build(report))
        return await self.model_planner.refine(plan, model)

"""Requirement strategy: turn a project suggestion into an executable plan.

The strategy package is deliberately read-only. It discovers impact, chooses
whether the change is an addition or a modification, and produces verification
criteria. Runtime change proposals and execution brokers own mutations.
"""

from Sprout.strategy.impact import ImpactAnalyzer
from Sprout.strategy.models import (
    ChangeMode,
    ImpactReport,
    ImpactSource,
    PlanStep,
    Requirement,
    StepKind,
    StrategyPlan,
    VerificationPlan,
)
from Sprout.strategy.pipeline import StrategyPipeline

__all__ = [
    "ChangeMode",
    "ImpactAnalyzer",
    "ImpactReport",
    "ImpactSource",
    "PlanStep",
    "Requirement",
    "StepKind",
    "StrategyPlan",
    "StrategyPipeline",
    "VerificationPlan",
]

"""Generate acceptance criteria for database, API, and code changes."""

from __future__ import annotations

from Sprout.strategy.models import (
    ImpactReport,
    VerificationCriterion,
    VerificationKind,
    VerificationPlan,
)


class VerificationPlanner:
    def build(self, impact: ImpactReport) -> VerificationPlan:
        criteria: list[VerificationCriterion] = []
        if impact.databases:
            criteria.extend(
                (
                    VerificationCriterion(
                        VerificationKind.DATABASE,
                        "schema",
                        "pytest -q -k database",
                        "schema and migration checks pass",
                    ),
                    VerificationCriterion(
                        VerificationKind.DATABASE,
                        "round_trip",
                        "pytest -q -k migration",
                        "write/read round-trip remains compatible",
                    ),
                )
            )
        if impact.interfaces:
            criteria.extend(
                (
                    VerificationCriterion(
                        VerificationKind.API,
                        "contract",
                        "pytest -q -k api",
                        "route/tool schema and response contract pass",
                    ),
                    VerificationCriterion(
                        VerificationKind.API,
                        "authorization",
                        "pytest -q -k approval",
                        "approval and scope boundaries remain enforced",
                    ),
                )
            )
        criteria.extend(
            (
                VerificationCriterion(
                    VerificationKind.CODE,
                    "regression",
                    "pytest -q",
                    "focused and regression tests pass",
                ),
                VerificationCriterion(
                    VerificationKind.CODE,
                    "lint",
                    "ruff check src",
                    "lint passes",
                ),
            )
        )
        return VerificationPlan(criteria=tuple(criteria))

"""Transport-free models for requirement decomposition."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from uuid import uuid4


class RequirementSource(StrEnum):
    USER = "user"
    PROJECT_SCAN = "project_scan"
    EVOLUTION = "evolution"


class ChangeMode(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class VerificationKind(StrEnum):
    DATABASE = "database"
    API = "api"
    CODE = "code"


class StepKind(StrEnum):
    """What a plan step is ultimately *for* — an intent label, nothing more.

    Do not read this as a statement about what the step's node may do. A step
    labelled EDIT describes an edit that a later AGENT node will make; it is
    not a node that writes. Every SUBTASK node is read-only by construction —
    its tool set is read/list/search/git-inspect — and measured behaviour
    bears that out: on a real plan the model labelled a pure read-only
    investigation as TEST. Use the node type for capability questions.
    """

    ANALYSIS = "analysis"
    EDIT = "edit"
    TEST = "test"
    OTHER = "other"


class ImpactSource(StrEnum):
    PROJECT_DATABASE = "project_database"
    PROJECT_SCAN = "project_scan"
    CROSS_VALIDATED = "cross_validated"


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One decomposable unit of work in a :class:`StrategyPlan`.

    ``target_paths`` is what makes a step actionable: the scheduler reads it
    to decide which resources the step's node may see. ``kind`` is only the
    model's intent label and carries no permission — see :class:`StepKind`.
    """

    description: str
    kind: StepKind = StepKind.OTHER
    target_paths: tuple[str, ...] = ()
    acceptance: str = ""

    @property
    def is_investigation(self) -> bool:
        """Whether the step is stated as pure investigation.

        A weaker claim than the old ``is_read_only`` name implied: it reports
        what the model said the step is for, not what its node may do. Every
        step's node is read-only regardless.
        """
        return self.kind is StepKind.ANALYSIS


@dataclass(frozen=True, slots=True)
class Requirement:
    """A normalized request from a user or project-evolution signal."""

    text: str
    source: RequirementSource = RequirementSource.USER
    id: str = field(default_factory=lambda: str(uuid4()))
    language: str = ""
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImpactItem:
    path: str
    category: str
    reason: str
    confidence: float = 0.0
    symbols: tuple[str, ...] = ()
    #: True when an actual requirement term appeared in the path. Most items on
    #: a real project are here only because they are project source, so this is
    #: the signal that separates "relevant" from "exists" — exposing it spares
    #: callers from re-deriving it out of the confidence score.
    matched: bool = False


@dataclass(frozen=True, slots=True)
class ImpactReport:
    items: tuple[ImpactItem, ...] = ()
    interfaces: tuple[str, ...] = ()
    databases: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    related_code: tuple[str, ...] = ()
    source: ImpactSource = ImpactSource.PROJECT_SCAN
    conflicts: tuple[str, ...] = ()

    def ranked_items(self) -> tuple[ImpactItem, ...]:
        """Items with requirement-matched files first.

        ``items`` is confidence-ordered, but on a real project almost
        everything shares the baseline score, so the tie-break falls through
        to the path and the ranking becomes alphabetical. That is how
        ``.uv-cache/...`` and then forty ``gateway/*`` files came to occupy the
        bounded resource list while the file the requirement actually named
        sat below the cut. Promotion by ``matched`` is what makes the bound
        cut noise instead of relevance.
        """
        return tuple(
            sorted(
                self.items,
                key=lambda item: (not item.matched, -item.confidence, item.path),
            )
        )

    def top_items(self, limit: int) -> tuple[ImpactItem, ...]:
        """The strongest ``limit`` items, matched-first, confidence-ordered.

        A scan of a real project returns one entry per source file, almost all
        of them at the baseline "this file exists" confidence — a Chinese
        requirement over an English codebase contributes a single keyword, so
        relevance scoring alone cannot separate them. Consumers that must
        bound their input (prompts, task specs, disk reads) use this instead
        of ``items``.
        """
        if limit <= 0:
            return ()
        return self.ranked_items()[:limit]

    def top_paths(self, limit: int) -> tuple[str, ...]:
        """Paths of :meth:`top_items`, deduplicated and order-preserving."""
        return tuple(dict.fromkeys(item.path for item in self.top_items(limit)))


@dataclass(frozen=True, slots=True)
class VerificationCriterion:
    kind: VerificationKind
    name: str
    command: str
    expected: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    criteria: tuple[VerificationCriterion, ...] = ()

    def for_kind(self, kind: VerificationKind) -> tuple[VerificationCriterion, ...]:
        return tuple(item for item in self.criteria if item.kind is kind)


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    requirement: Requirement
    mode: ChangeMode
    impact: ImpactReport
    verification: VerificationPlan
    implementation_steps: tuple[str, ...] = ()
    test_files: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    model_strategy: str = ""
    model_name: str = ""
    #: Structured decomposition. Kept last and defaulted so the positional
    #: construction in ``RequirementPlanner`` stays valid. ``implementation_steps``
    #: above remains the human-readable projection of this field.
    steps: tuple[PlanStep, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible data for CLI/API consumers."""
        return {
            "requirement": {
                "id": self.requirement.id,
                "text": self.requirement.text,
                "source": self.requirement.source.value,
                "language": self.requirement.language,
            },
            "mode": self.mode.value,
            "impact": {
                "interfaces": list(self.impact.interfaces),
                "databases": list(self.impact.databases),
                "tests": list(self.impact.tests),
                "related_code": list(self.impact.related_code),
                "source": self.impact.source.value,
                "conflicts": list(self.impact.conflicts),
                "items": [asdict(item) for item in self.impact.items],
            },
            "verification": [asdict(criterion) for criterion in self.verification.criteria],
            "implementation_steps": list(self.implementation_steps),
            "test_files": list(self.test_files),
            "risks": list(self.risks),
            "model_strategy": self.model_strategy,
            "model_name": self.model_name,
            "steps": [asdict(step) for step in self.steps],
        }

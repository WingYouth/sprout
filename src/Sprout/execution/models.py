"""Execution result and change models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class ChangeProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    command: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    allowed: bool = True
    error: str | None = None
    #: Whether the command came from the server-side allowlist (AUTHZ §6.1).
    allowlisted: bool = False
    #: How many credentials were masked in the captured output (AUTHZ §4.2).
    redactions: int = 0
    #: Set when the command was withheld pending human approval. The caller
    #: can park on this and retry once the grant exists, rather than treating
    #: "not yet allowed" as "refused".
    approval_id: str | None = None

    @property
    def needs_approval(self) -> bool:
        return self.approval_id is not None


@dataclass(frozen=True, slots=True)
class TestResult:
    name: str
    passed: bool
    output: str = ""
    duration_ms: float = 0.0
    #: False when the command never ran (the policy withheld approval), which
    #: ``passed=False`` alone cannot express. A gate that only sees ``passed``
    #: treats "nobody looked" as "known bad" and refuses to land a change that
    #: was never actually judged.
    executed: bool = True

    @property
    def failed(self) -> bool:
        """Ran and did not pass. Unverified is explicitly not a failure."""
        return self.executed and not self.passed


@dataclass(frozen=True, slots=True)
class SandboxRef:
    id: str
    kind: str
    root: Path
    worktree_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DiffResult:
    path: str
    diff_text: str = ""
    old_hash: str | None = None
    new_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeProposal:
    task_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    sandbox_ref: SandboxRef | None = None
    files_changed: tuple[str, ...] = ()
    test_results: tuple[TestResult, ...] = ()
    diffs: tuple[DiffResult, ...] = ()
    risk: str = "medium"
    required_capability_diff: tuple[str, ...] = ()
    rollback_plan: str = ""
    status: ChangeProposalStatus = ChangeProposalStatus.PENDING
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ApplyResult:
    proposal_id: str
    applied: bool
    reason: str = ""
    base_commit: str = ""
    applied_commit: str = ""


@dataclass(frozen=True, slots=True)
class FileResult:
    path: str
    wrote: bool
    reason: str = ""
    #: The classified kind the decision was made against (AUTHZ §3.2).
    resource_kind: str = ""
    #: File body returned by a read; empty for write/delete results.
    content: str = ""


@dataclass(frozen=True, slots=True)
class NetworkResult:
    url: str
    status_code: int | None = None
    body: str = ""
    allowed: bool = True
    reason: str = ""
    redactions: int = 0


@dataclass(frozen=True, slots=True)
class DatabaseResult:
    database: str
    rows: tuple[tuple[object, ...], ...] = ()
    rowcount: int = 0
    allowed: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class GitResult:
    action: str
    output: str = ""
    allowed: bool = True
    reason: str = ""

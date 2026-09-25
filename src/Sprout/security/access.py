"""Access-control domain models for real I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from Sprout.gateway.identity import Principal
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceRef


class ActionType(StrEnum):
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_DELETE = "file.delete"
    PROCESS_RUN = "process.run"
    NETWORK_GET = "network.get"
    NETWORK_POST = "network.post"
    DB_READ = "db.read"
    DB_WRITE = "db.write"
    GIT_STATUS = "git.status"
    GIT_LOG = "git.log"
    GIT_BRANCH = "git.branch"
    GIT_DIFF = "git.diff"
    GIT_ADD = "git.add"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"
    GIT_PULL = "git.pull"
    SECRET_READ = "secret.read"
    SECRET_USE = "secret.use"
    # Skill lifecycle (design §8.4): installing brings third-party content in,
    # enabling lets it reach the prompt, so both are policy-visible actions.
    SKILL_INSTALL = "skill.install"
    SKILL_ENABLE = "skill.enable"


class AccessDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    SANDBOX_ONLY = "sandbox_only"
    ALLOW_REDACTED = "allow_redacted"


@dataclass(frozen=True, slots=True)
class ActionRequest:
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    actor: Principal = field(default_factory=lambda: Principal(user_id="system"))
    action: ActionType = ActionType.FILE_READ
    resource: ResourceRef | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    scope: DelegationScope = field(default_factory=DelegationScope)
    idempotency_key: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """One decision, with its provenance.

    ``matched_rules`` carries ``<layer>:<rule id>`` entries (``floor:rm-root``,
    ``org:deny:git push --force*``, ``matrix:file.write:secret``) so the audit
    stream and the approval prompt can answer "why was this allowed".
    ``approval_id`` points at the :class:`~Sprout.security.approval.ApprovalRecord`
    that satisfied (or is required for) the request; approval state lives in the
    operational store, never in the decision.
    """

    decision: AccessDecision
    reason: str = ""
    redactions: tuple[str, ...] = ()
    matched_rules: tuple[str, ...] = ()
    approval_id: str = ""

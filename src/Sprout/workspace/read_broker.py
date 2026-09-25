"""Policy-controlled file reads (AUTHZ §3.1-§3.3).

Every read is classified against the workspace root with the shared rule table,
so ``.env`` is refused even when the caller declared it as plain source, and
``ALLOW_REDACTED`` is executed *here*: the file is read and then scrubbed by the
runtime-wide redactor, with the number of masked matches returned for the audit
record.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.engine import PolicyEngine
from Sprout.security.redact import Redactor
from Sprout.task.models import DelegationScope
from Sprout.workspace.classifier import classify, is_device_namespace
from Sprout.workspace.models import ReadPlan, ResourceRef, Workspace


@dataclass(frozen=True, slots=True)
class ReadResult:
    resource: ResourceRef
    decision: AccessDecision
    content: str = ""
    error: str | None = None
    #: How many credentials were masked during an ALLOW_REDACTED read.
    redaction_count: int = 0


class ReadBroker:
    """Executes only file reads already allowed by the PolicyEngine."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        max_bytes: int = 20_000,
        redactor: Redactor | None = None,
        classify_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._policy = policy
        self._max_bytes = max_bytes
        self._redactor = redactor or Redactor()
        self._classify_overrides = dict(classify_overrides or {})

    @property
    def redactor(self) -> Redactor:
        return self._redactor

    async def read(
        self,
        workspace: Workspace,
        plan: ReadPlan,
        *,
        scope: DelegationScope | None = None,
    ) -> list[ReadResult]:
        """Execute the plan.

        ``scope`` is the task's caller-granted permission set (AUTHZ §2.2). It
        used to be left out of every `ActionRequest`, which made
        ``PolicyEngine``'s scope check a no-op: a channel that granted only
        ``file.read`` was never actually limited to reading.
        """
        effective_scope = scope if scope is not None else DelegationScope()
        results: list[ReadResult] = []
        for resource in plan.resources:
            if is_device_namespace(resource.path):
                results.append(
                    ReadResult(
                        resource,
                        AccessDecision.DENY,
                        error="Device-namespace path is not allowed",
                    )
                )
                continue
            target = self._safe_target(workspace, resource.path)
            if target is None:
                results.append(
                    ReadResult(
                        resource,
                        AccessDecision.DENY,
                        error="Path escapes workspace boundary",
                    )
                )
                continue
            classified = self._classify(workspace, target, resource)
            request = ActionRequest(
                task_id=plan.task_id,
                action=ActionType.FILE_READ,
                resource=classified,
                scope=effective_scope,
            )
            decision = self._policy.decide(request)
            if decision.decision is AccessDecision.DENY:
                results.append(ReadResult(classified, decision.decision, error=decision.reason))
                continue
            try:
                content = await asyncio.to_thread(self._read_text, target)
            except OSError as exc:
                results.append(
                    ReadResult(
                        classified,
                        decision.decision,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if decision.decision is AccessDecision.ALLOW_REDACTED:
                redacted = self._redactor.redact(content)
                results.append(
                    ReadResult(
                        classified,
                        decision.decision,
                        content=redacted.text,
                        redaction_count=redacted.count,
                    )
                )
            else:
                results.append(ReadResult(classified, decision.decision, content=content))
        return results

    def _classify(
        self, workspace: Workspace, target: Path, resource: ResourceRef
    ) -> ResourceRef:
        """Re-classify from the path; the declared kind is a hint, not evidence."""
        kind = classify(
            target,
            workspace_root=workspace.root,
            overrides=self._classify_overrides,
        )
        if kind is resource.kind:
            return resource
        return ResourceRef(
            workspace_id=resource.workspace_id,
            path=resource.path,
            revision=resource.revision,
            content_hash=resource.content_hash,
            kind=kind,
        )

    @staticmethod
    def _safe_target(workspace: Workspace, relative_path: str) -> Path | None:
        """Resolve a workspace-relative path, rejecting escapes via ``..`` or symlinks.

        Device-namespace paths are refused before ``resolve()`` runs, because
        resolving an ``\\\\?\\UNC\\`` path can trigger outbound SMB
        authentication (see :func:`~Sprout.workspace.classifier.is_device_namespace`).
        """
        if is_device_namespace(relative_path):
            return None
        root = Path(workspace.root).resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    def _read_text(self, path: Path) -> str:
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            return "[binary content]"
        return data[: self._max_bytes].decode("utf-8", errors="replace")

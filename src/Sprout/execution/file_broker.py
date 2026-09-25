"""Policy-controlled sandbox file writes and deletes (AUTHZ §3.2).

Writes used to be ``SANDBOX_ONLY`` regardless of what the file *was*, which
meant a sandbox could overwrite ``.env`` or a private key. The target is now
classified against the sandbox root (``workspace/classifier.py``) and the kind
drives the decision: SECRET/EXTERNAL are denied outright, SENSITIVE needs a
human, everything else stays sandbox-first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.events import FILE_DELETED, Event
from Sprout.execution.models import FileResult, SandboxRef
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.engine import PolicyEngine
from Sprout.task.models import DelegationScope
from Sprout.workspace.classifier import classify, is_device_namespace
from Sprout.workspace.models import ResourceKind, ResourceRef

if TYPE_CHECKING:
    from Sprout.events import EventBus


class FileBroker:
    """Writes files only inside an explicit sandbox root."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        classify_overrides: Mapping[str, str] | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._policy = policy
        self._classify_overrides = dict(classify_overrides or {})
        self._events = events

    def _classify(self, target: Path, sandbox: SandboxRef) -> ResourceKind:
        return classify(
            target,
            workspace_root=sandbox.root,
            overrides=self._classify_overrides,
        )

    async def write_text(
        self,
        sandbox: SandboxRef,
        relative_path: str | Path,
        content: str,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> FileResult:
        target = self._safe_target(sandbox, relative_path)
        if target is None:
            return FileResult(path=str(relative_path), wrote=False, reason="Path escapes sandbox")

        kind = self._classify(target, sandbox)
        request = ActionRequest(
            task_id=task_id,
            action=ActionType.FILE_WRITE,
            resource=ResourceRef(
                workspace_id=sandbox.id,
                path=target.as_posix(),
                kind=kind,
            ),
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        if decision.decision is not AccessDecision.SANDBOX_ONLY:
            return FileResult(
                path=str(relative_path),
                wrote=False,
                reason=decision.reason,
                resource_kind=kind.value,
            )

        await asyncio.to_thread(self._write, target, content)
        return FileResult(path=str(relative_path), wrote=True, resource_kind=kind.value)

    async def read_text(
        self,
        sandbox: SandboxRef,
        relative_path: str | Path,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> FileResult:
        target = self._safe_target(sandbox, relative_path)
        if target is None:
            return FileResult(path=str(relative_path), wrote=False, reason="Path escapes sandbox")

        kind = self._classify(target, sandbox)
        request = ActionRequest(
            task_id=task_id,
            action=ActionType.FILE_READ,
            resource=ResourceRef(
                workspace_id=sandbox.id,
                path=target.as_posix(),
                kind=kind,
            ),
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        if decision.decision not in {AccessDecision.ALLOW, AccessDecision.ALLOW_REDACTED}:
            return FileResult(
                path=str(relative_path),
                wrote=False,
                reason=decision.reason,
                resource_kind=kind.value,
            )

        content = await asyncio.to_thread(self._read, target)
        return FileResult(
            path=str(relative_path),
            wrote=True,
            resource_kind=kind.value,
            content=content,
        )

    async def exists(
        self,
        sandbox: SandboxRef,
        relative_path: str | Path,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> bool:
        """Return whether ``relative_path`` exists inside the sandbox root."""
        target = self._safe_target(sandbox, relative_path)
        if target is None:
            return False
        return await asyncio.to_thread(Path.exists, target)

    async def delete(
        self,
        sandbox: SandboxRef,
        relative_path: str | Path,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> FileResult:
        target = self._safe_target(sandbox, relative_path)
        if target is None:
            return FileResult(path=str(relative_path), wrote=False, reason="Path escapes sandbox")
        kind = self._classify(target, sandbox)
        request = ActionRequest(
            task_id=task_id,
            action=ActionType.FILE_DELETE,
            resource=ResourceRef(
                workspace_id=sandbox.id,
                path=target.as_posix(),
                kind=kind,
            ),
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        if decision.decision is not AccessDecision.SANDBOX_ONLY:
            return FileResult(
                path=str(relative_path),
                wrote=False,
                reason=decision.reason,
                resource_kind=kind.value,
            )
        await asyncio.to_thread(self._delete, target)
        if self._events is not None:
            await self._events.publish(
                Event(
                    FILE_DELETED,
                    {
                        "task_id": task_id,
                "sandbox_id": sandbox.id,
                        "path": target.relative_to(Path(sandbox.root).resolve()).as_posix(),
                        "resource_kind": kind.value,
                    },
                )
            )
        return FileResult(path=str(relative_path), wrote=True, resource_kind=kind.value)

    @staticmethod
    def _safe_target(sandbox: SandboxRef, relative_path: str | Path) -> Path | None:
        """Resolve a sandbox-relative path, refusing device-namespace input first."""
        if is_device_namespace(relative_path):
            return None
        root = Path(sandbox.root).resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except OSError as exc:
            return f"read failed: {exc}"

    @staticmethod
    def _delete(path: Path) -> None:
        path.unlink(missing_ok=True)

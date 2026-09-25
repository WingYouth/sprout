"""Policy-controlled HTTP requests (AUTHZ §6.3).

``network.get`` is ``ALLOW`` in the matrix, but the URL still passes through
:class:`~Sprout.security.net_guard.NetworkGuard` first: private, loopback,
link-local (``169.254.169.254``), and CGNAT targets are refused so a fetched
page cannot be turned into an SSRF primitive against the host or the cloud
metadata service.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from Sprout.execution.models import NetworkResult
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.approval import ApprovalManager
from Sprout.security.engine import PolicyEngine
from Sprout.security.net_guard import NetworkGuard, NetworkVerdict
from Sprout.security.secret_broker import SecretBroker
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace

if TYPE_CHECKING:
    from Sprout.events import EventBus
    from Sprout.security.audit import SecurityAuditLog


class NetworkBroker:
    """Executes HTTP requests only after a policy decision and a URL guard."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        approvals: ApprovalManager | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        guard: NetworkGuard | None = None,
        secrets: SecretBroker | None = None,
        events: EventBus | None = None,
        audit: SecurityAuditLog | None = None,
    ) -> None:
        self._policy = policy
        self._approvals = approvals
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._guard = guard
        self._secrets = secrets or SecretBroker()
        self._events = events
        self._audit = audit

    async def get(
        self,
        workspace: Workspace,
        url: str,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> NetworkResult:
        blocked = await self._guard_url(url)
        if blocked is not None:
            return blocked
        decision = await self._decide(workspace, url, ActionType.NETWORK_GET, {}, task_id, scope)
        if decision is not AccessDecision.ALLOW:
            return NetworkResult(url=url, allowed=False, reason="Network GET not allowed")
        return await self._request("GET", url)

    async def post(
        self,
        workspace: Workspace,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> NetworkResult:
        blocked = await self._guard_url(url)
        if blocked is not None:
            return blocked
        arguments = {"url": url, "json": dict(json or {})}
        decision = await self._decide(
            workspace, url, ActionType.NETWORK_POST, arguments, task_id, scope
        )
        if decision is AccessDecision.REQUIRE_APPROVAL:
            if self._approvals is None or not await self._approvals.is_approved(
                ActionType.NETWORK_POST.value,
                arguments,
                task_id=task_id,
            ):
                return NetworkResult(
                    url=url,
                    allowed=False,
                    reason="Network POST requires approval",
                )
        elif decision is not AccessDecision.ALLOW:
            return NetworkResult(url=url, allowed=False, reason="Network POST not allowed")
        return await self._request("POST", url, json=json)

    async def download(
        self,
        workspace: Workspace,
        url: str,
        destination: str | Path,
        *,
        task_id: str = "",
    ) -> NetworkResult:
        """Stream a guarded GET response to a file without following redirects."""
        blocked = await self._guard_url(url)
        if blocked is not None:
            return blocked
        decision = await self._decide(workspace, url, ActionType.NETWORK_GET, {}, task_id)
        if decision is not AccessDecision.ALLOW:
            return NetworkResult(url=url, allowed=False, reason="Network GET not allowed")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        return NetworkResult(
                            url=url,
                            allowed=False,
                            reason=f"Download blocked: redirects to "
                            f"{response.headers.get('location', '')}",
                        )
                    response.raise_for_status()
                    with target.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
            return NetworkResult(
                url=url,
                status_code=response.status_code,
                allowed=True,
                body=str(target),
            )
        except Exception as exc:  # noqa: BLE001 - network/download errors are results
            return NetworkResult(
                url=url,
                allowed=False,
                reason=f"Download failed: {type(exc).__name__}: {exc}",
            )

    async def _guard_url(self, url: str) -> NetworkResult | None:
        """Return a refusal when the URL targets a non-routable address."""
        if self._guard is None:
            return None
        verdict = await self._guard.acheck(url)
        if verdict.allowed:
            return None
        self._record_blocked(url, verdict)
        return NetworkResult(url=url, allowed=False, reason=verdict.reason)

    def _record_blocked(self, url: str, verdict: NetworkVerdict) -> None:
        """Audit a guard refusal (AUTHZ §7.4).

        ``network.blocked`` is declared ``bus_event=False`` in the catalog: it
        belongs on the security audit stream, not the event bus. Recording
        never raises into the caller's path.
        """
        if self._audit is None:
            return
        from Sprout.security.audit import KIND_NETWORK_BLOCKED

        self._audit.record(
            KIND_NETWORK_BLOCKED,
            {
                "url": url,
                "host": verdict.host,
                "reason": verdict.reason,
            },
        )

    async def _decide(
        self,
        workspace: Workspace,
        url: str,
        action: ActionType,
        arguments: dict[str, Any],
        task_id: str,
        scope: DelegationScope | None = None,
    ) -> AccessDecision:
        resource = ResourceRef(
            workspace_id=workspace.id,
            path=url,
            kind=ResourceKind.OTHER,
        )
        request = ActionRequest(
            task_id=task_id,
            action=action,
            resource=resource,
            arguments=arguments,
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        return decision.decision

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
    ) -> NetworkResult:
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.request(method, url, json=json)
            body = self._secrets.redact_result(response.text)
            return NetworkResult(
                url=url,
                status_code=response.status_code,
                body=body.text,
                allowed=True,
                redactions=body.count,
            )

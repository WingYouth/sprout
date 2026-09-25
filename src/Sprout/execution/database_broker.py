"""Policy-controlled SQLite database access."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.execution.models import DatabaseResult
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.engine import PolicyEngine
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace

if TYPE_CHECKING:
    from Sprout.events import EventBus


class DatabaseBroker:
    """Executes SQLite reads/writes only after a policy decision."""

    def __init__(self, policy: PolicyEngine, *, events: EventBus | None = None) -> None:
        self._policy = policy
        self._events = events

    async def query(
        self,
        workspace: Workspace,
        database: str | Path,
        sql: str,
        parameters: tuple[object, ...] = (),
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> DatabaseResult:
        decision = await self._decide(workspace, database, ActionType.DB_READ, sql, task_id, scope)
        if decision is not AccessDecision.ALLOW:
            return DatabaseResult(database=str(database), allowed=False, reason=decision.value)
        return await asyncio.to_thread(self._query, database, sql, parameters)

    async def execute(
        self,
        workspace: Workspace,
        database: str | Path,
        sql: str,
        parameters: tuple[object, ...] = (),
        *,
        sandbox: bool = False,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> DatabaseResult:
        decision = await self._decide(workspace, database, ActionType.DB_WRITE, sql, task_id, scope)
        if decision is AccessDecision.SANDBOX_ONLY and not sandbox:
            return DatabaseResult(
                database=str(database),
                allowed=False,
                reason="Database write is sandbox-only",
            )
        if decision is AccessDecision.SANDBOX_ONLY:
            return await asyncio.to_thread(self._execute, database, sql, parameters)
        return DatabaseResult(database=str(database), allowed=False, reason=decision.value)

    async def _decide(
        self,
        workspace: Workspace,
        database: str | Path,
        action: ActionType,
        sql: str,
        task_id: str,
        scope: DelegationScope | None = None,
    ) -> AccessDecision:
        """Ask the policy engine, carrying the statement text with the request.

        The statement used to be left out of ``arguments``, so no layer ever saw
        it: ``PolicyRule.argument_guards`` could not target it and the hard floor
        (which scans ``command``/``cmd``/``argv``/``script``/``sql``) had nothing
        to read. A single ``ATTACH DATABASE '<abs path>'`` therefore reached any
        file on disk through an action the policy had rated ``ALLOW`` (audit R8).
        The database *path* is still the resource; the statement rides along as
        an argument, exactly as a command line rides along for ``process.run``.
        """
        resource = ResourceRef(
            workspace_id=workspace.id,
            path=str(database),
            kind=ResourceKind.DATA,
        )
        request = ActionRequest(
            task_id=task_id,
            action=action,
            resource=resource,
            arguments={"sql": sql},
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        return decision.decision

    @staticmethod
    def _query(
        database: str | Path,
        sql: str,
        parameters: tuple[object, ...],
    ) -> DatabaseResult:
        connection = sqlite3.connect(str(database))
        try:
            rows = connection.execute(sql, parameters).fetchall()
            return DatabaseResult(database=str(database), rows=tuple(rows))
        finally:
            connection.close()

    @staticmethod
    def _execute(
        database: str | Path,
        sql: str,
        parameters: tuple[object, ...],
    ) -> DatabaseResult:
        connection = sqlite3.connect(str(database))
        try:
            cursor = connection.execute(sql, parameters)
            connection.commit()
            return DatabaseResult(
                database=str(database),
                rowcount=cursor.rowcount,
            )
        finally:
            connection.close()

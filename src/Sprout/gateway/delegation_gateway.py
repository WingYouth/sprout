"""External Agent delegation gateway."""

from __future__ import annotations

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import DelegationScope


class DelegationGateway:
    """Executes tasks delegated by external agents with an explicit scope."""

    def __init__(self, runtime: Runtime) -> None:
        self._gateway = RuntimeGateway(runtime, transport="delegation")

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str,
        caller_id: str,
        scope: DelegationScope,
    ) -> GatewayResponse:
        return await self._gateway.execute(
            GatewayRequest(
                transport="delegation",
                instruction=instruction,
                caller=Principal(user_id=caller_id),
                workspace_id=workspace_id,
                delegation_scope=scope,
            )
        )

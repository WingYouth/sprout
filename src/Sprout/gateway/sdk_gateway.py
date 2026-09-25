"""Python SDK gateway for embedding SEMA in another application."""

from __future__ import annotations

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import DelegationScope


class SDKGateway:
    """Runtime SDK facade used by Python applications."""

    def __init__(self, runtime: Runtime) -> None:
        self._gateway = RuntimeGateway(runtime, transport="sdk")

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str,
        caller_id: str = "sdk-user",
        delegation_scope: DelegationScope | None = None,
    ) -> GatewayResponse:
        return await self._gateway.execute(
            GatewayRequest(
                transport="sdk",
                instruction=instruction,
                caller=Principal(user_id=caller_id),
                workspace_id=workspace_id,
                delegation_scope=delegation_scope or DelegationScope(),
            )
        )

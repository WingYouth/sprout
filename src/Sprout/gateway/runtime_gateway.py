"""Runtime-backed gateway facade.

Transport adapters can call this facade instead of touching Runtime internals
directly. It converts gateway input into Tasks and returns a GatewayResponse.
"""

from __future__ import annotations

from Sprout.events import AUTH_ROLES_DISCARDED, Event
from Sprout.gateway.identity import discarded_roles
from Sprout.gateway.task_adapter import (
    GatewayRequest,
    GatewayResponse,
    TaskAdapter,
)
from Sprout.message.models import Message
from Sprout.runtime.runtime import Runtime


class RuntimeGateway:
    """Small interface-layer facade over one Runtime instance."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        transport: str = "gateway",
        adapter: TaskAdapter | None = None,
    ) -> None:
        self._runtime = runtime
        self._transport = transport
        self._adapter = adapter or TaskAdapter()

    async def execute(self, request: GatewayRequest) -> GatewayResponse:
        task = self._adapter.to_task(request)
        result = await self._runtime.execute(task)
        return GatewayResponse(
            task_id=result.task_id,
            status=result.status.value,
            content=result.content,
            metadata=dict(result.metrics),
        )

    async def execute_message(self, message: Message) -> GatewayResponse:
        # Identity never comes from the message body (AUTHZ §2.1): roles found in
        # ``message.metadata`` are discarded and the attempt is audited.
        roles = discarded_roles(message)
        if roles:
            await self._runtime.events.publish(
                Event(
                    AUTH_ROLES_DISCARDED,
                    {
                        "user_id": message.user_id,
                        "channel": message.channel,
                        "roles": list(roles),
                    },
                    message.id,
                )
            )
        request = self._adapter.from_message(
            message,
            workspace_id=message.metadata.get("workspace_id", ""),
        )
        return await self.execute(request)

    async def handle_message(self, message: Message) -> GatewayResponse:
        outbound = await self._runtime.handle(message)
        return GatewayResponse(
            task_id=outbound.session_id or "",
            status="completed",
            content=outbound.content,
            metadata={
                "session_id": outbound.session_id,
                "correlation_id": outbound.correlation_id,
                **outbound.metadata,
            },
        )

    async def handle_stream(self, message: Message):
        async for chunk in self._runtime.handle_stream(message):
            yield chunk

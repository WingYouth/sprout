"""Concrete transport gateways for CLI, Web, and MCP."""

from __future__ import annotations

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.message.models import Message
from Sprout.runtime.runtime import Runtime


class CLIGateway:
    def __init__(self, runtime: Runtime) -> None:
        self._gateway = RuntimeGateway(runtime, transport="cli")

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str = "",
        user_id: str = "cli-user",
    ) -> GatewayResponse:
        from Sprout.gateway.temporal_bridge import submit_gateway_workflow

        await submit_gateway_workflow(
            {
                "transport": "cli",
                "id": workspace_id or "cli",
                "instruction": instruction,
                "user_id": user_id,
            }
        )
        return await self._gateway.execute(
            GatewayRequest(
                transport="cli",
                instruction=instruction,
                caller=Principal(user_id=user_id),
                workspace_id=workspace_id,
            )
        )

    async def handle_message(self, message: Message) -> GatewayResponse:
        return await self._gateway.handle_message(message)

    async def handle_stream(self, message: Message):
        async for chunk in self._gateway.handle_stream(message):
            yield chunk


class WebGateway:
    def __init__(self, runtime: Runtime) -> None:
        self._gateway = RuntimeGateway(runtime, transport="web")

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str = "",
        user_id: str = "web-user",
    ) -> GatewayResponse:
        from Sprout.gateway.temporal_bridge import submit_gateway_workflow

        await submit_gateway_workflow(
            {
                "transport": "web",
                "id": workspace_id or "web",
                "instruction": instruction,
                "user_id": user_id,
            }
        )
        return await self._gateway.execute(
            GatewayRequest(
                transport="web",
                instruction=instruction,
                caller=Principal(user_id=user_id),
                workspace_id=workspace_id,
            )
        )

    async def handle_message(self, message: Message) -> GatewayResponse:
        return await self._gateway.handle_message(message)

    async def handle_stream(self, message: Message):
        async for chunk in self._gateway.handle_stream(message):
            yield chunk


class MCPGateway:
    def __init__(self, runtime: Runtime) -> None:
        self._gateway = RuntimeGateway(runtime, transport="mcp")

    async def execute(
        self,
        instruction: str,
        *,
        workspace_id: str = "",
        user_id: str = "mcp-client",
    ) -> GatewayResponse:
        from Sprout.gateway.temporal_bridge import submit_gateway_workflow

        await submit_gateway_workflow(
            {
                "transport": "mcp",
                "id": workspace_id or "mcp",
                "instruction": instruction,
                "user_id": user_id,
            }
        )
        return await self._gateway.execute(
            GatewayRequest(
                transport="mcp",
                instruction=instruction,
                caller=Principal(user_id=user_id),
                workspace_id=workspace_id,
            )
        )

    async def handle_message(self, message: Message) -> GatewayResponse:
        return await self._gateway.handle_message(message)

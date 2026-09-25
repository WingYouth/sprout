"""Tests for the V1.0 interface-layer Task adapter."""

from __future__ import annotations

from Sprout.gateway.identity import Principal
from Sprout.gateway.task_adapter import GatewayRequest, TaskAdapter
from Sprout.message.models import Message
from Sprout.task.models import DelegationScope


def test_gateway_request_becomes_task() -> None:
    request = GatewayRequest(
        transport="mcp",
        instruction="scan auth flow",
        caller=Principal(user_id="external-agent"),
        workspace_id="ws-1",
        delegation_scope=DelegationScope(allowed_actions=frozenset({"file.read"})),
    )

    task = TaskAdapter().to_task(request)

    assert task.source == "mcp"
    assert task.workspace_id == "ws-1"
    assert task.actor.user_id == "external-agent"
    assert task.delegation_scope.permits("file.read")


def test_message_becomes_gateway_request() -> None:
    message = Message(
        content="explain login",
        channel="cli",
        user_id="human",
        metadata={"roles": ["developer"]},
    )

    request = TaskAdapter().from_message(message, workspace_id="ws-1")

    assert request.transport == "cli"
    assert request.workspace_id == "ws-1"
    assert request.caller.user_id == "human"

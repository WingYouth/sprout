"""Gateway layer: transport boundary, identity, and gateway registry."""

from Sprout.gateway.base import Gateway
from Sprout.gateway.identity import Principal, principal_from_message
from Sprout.gateway.registry import GatewayRegistry
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse, TaskAdapter

__all__ = [
    "Gateway",
    "GatewayRegistry",
    "GatewayRequest",
    "GatewayResponse",
    "Principal",
    "TaskAdapter",
    "principal_from_message",
]

"""Gateway protocol: transport adapters exchange unified messages only."""

from typing import Protocol

from Sprout.message.models import Message, OutboundMessage


class Gateway(Protocol):
    """A gateway never knows about agents; it maps its transport onto Message."""

    async def receive(self) -> Message: ...
    async def send(self, message: OutboundMessage) -> None: ...

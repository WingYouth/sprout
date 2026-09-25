"""Runtime middleware chain applied around every online turn."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from Sprout.message.models import Message, OutboundMessage

logger = logging.getLogger("sprout.runtime")

class Middleware(Protocol):
    async def before(self, message: Message) -> Message: ...
    async def after(self, message: Message, outbound: OutboundMessage) -> OutboundMessage: ...


@dataclass(slots=True)
class NoopMiddleware:
    async def before(self, message: Message) -> Message:
        return message

    async def after(self, message: Message, outbound: OutboundMessage) -> OutboundMessage:
        return outbound


class LoggingMiddleware:
    """Logs one line per turn; useful in front of every entry point.

    Plain class (not a slots dataclass): it carries a logger handle set in
    ``__init__``, which ``slots=True`` dataclasses cannot do.
    """

    def __init__(self, *, logger: logging.Logger = logger) -> None:
        self._logger = logger

    async def before(self, message: Message) -> Message:
        self._logger.info(
            "turn start: message=%s channel=%s user=%s session=%s",
            message.id,
            message.channel,
            message.user_id,
            message.session_id,
        )
        return message

    async def after(self, message: Message, outbound: OutboundMessage) -> OutboundMessage:
        self._logger.info(
            "turn end: message=%s session=%s correlation=%s",
            message.id,
            outbound.session_id,
            outbound.correlation_id,
        )
        return outbound


@dataclass(slots=True)
class MiddlewareChain:
    middlewares: tuple[Middleware, ...] = field(default_factory=tuple)

    def add(self, middleware: Middleware) -> None:
        self.middlewares = (*self.middlewares, middleware)

    async def before(self, message: Message) -> Message:
        for middleware in self.middlewares:
            message = await middleware.before(message)
        return message

    async def after(self, message: Message, outbound: OutboundMessage) -> OutboundMessage:
        for middleware in reversed(self.middlewares):
            outbound = await middleware.after(message, outbound)
        return outbound

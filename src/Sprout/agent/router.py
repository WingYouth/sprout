"""AgentRouter: picks the agent for a message using rules or a selector."""

from __future__ import annotations

from collections.abc import Callable

from Sprout.agent.base import Agent
from Sprout.message.models import Message
from Sprout.registry.base import Registry
from Sprout.registry.routes import RouteRegistry

RouteSelector = Callable[[Message], str]


class AgentRouter:
    def __init__(
        self,
        agents: Registry[Agent],
        *,
        default: str,
        selector: RouteSelector | None = None,
        rules: RouteRegistry | None = None,
    ) -> None:
        self._agents = agents
        self._default = default
        self._selector = selector
        self._rules = rules

    @property
    def default(self) -> str:
        return self._default

    def route(self, message: Message) -> Agent:
        name: str | None = None
        if self._selector is not None:
            name = self._selector(message)
        if name is None and self._rules is not None:
            name = self._rules.match(message)
        if name is None or not self._agents.contains(name):
            name = self._default
        return self._agents.get(name)

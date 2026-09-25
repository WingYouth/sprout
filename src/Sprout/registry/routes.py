"""Message-based routing rules consumed by the AgentRouter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from Sprout.message.models import Message

RoutePredicate = Callable[[Message], bool]


@dataclass(frozen=True, slots=True)
class RouteRule:
    name: str
    agent: str
    predicate: RoutePredicate
    description: str = ""


def keyword_route(
    name: str, agent: str, keywords: tuple[str, ...], *, casefold: bool = True
) -> RouteRule:
    """Route a message to ``agent`` when its content contains any keyword."""

    def predicate(message: Message) -> bool:
        content = message.content.casefold() if casefold else message.content
        return any(keyword in content for keyword in keywords)

    return RouteRule(name=name, agent=agent, predicate=predicate)


@dataclass(slots=True)
class RouteRegistry:
    rules: list[RouteRule] = field(default_factory=list)

    def add(self, rule: RouteRule, *, replace: bool = False) -> None:
        if replace:
            self.rules = [r for r in self.rules if r.name != rule.name]
        elif any(r.name == rule.name for r in self.rules):
            raise ValueError(f"Route rule already exists: {rule.name}")
        self.rules.append(rule)

    def match(self, message: Message) -> str | None:
        for rule in self.rules:
            if rule.predicate(message):
                return rule.agent
        return None

    def list(self) -> list[RouteRule]:
        return list(self.rules)

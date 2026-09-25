"""Planner protocol reserved for plan-then-execute agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from Sprout.context.context import AgentContext
    from Sprout.message.models import Message


@dataclass(frozen=True, slots=True)
class Plan:
    goal: str
    steps: tuple[str, ...] = ()


class Planner(Protocol):
    async def plan(self, message: Message, context: AgentContext) -> Plan: ...


@dataclass(slots=True)
class DirectPlanner:
    """Single-step planner; the reactive AgentLoop needs no upfront plan."""

    async def plan(self, message: Message, context: AgentContext) -> Plan:
        return Plan(goal=message.content, steps=("respond",))

"""Named prompt templates that gateways (MCP, Web) can expose."""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.registry.base import Registry


@dataclass(frozen=True, slots=True)
class PromptArgument:
    name: str
    description: str = ""
    required: bool = False


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A template with ``{argument}`` placeholders matching its declared arguments."""

    name: str
    template: str
    description: str = ""
    arguments: tuple[PromptArgument, ...] = ()


class PromptRegistry:
    def __init__(self) -> None:
        self._registry: Registry[PromptTemplate] = Registry()

    def register(self, template: PromptTemplate, *, replace: bool = True) -> None:
        self._registry.register(template.name, template, replace=replace)

    def get(self, name: str) -> PromptTemplate:
        return self._registry.get(name)

    def list(self) -> dict[str, PromptTemplate]:
        return self._registry.list()

    def render(self, name: str, **kwargs: str) -> str:
        template = self.get(name)
        missing = [
            argument.name
            for argument in template.arguments
            if argument.required and argument.name not in kwargs
        ]
        if missing:
            raise ValueError(f"Missing required prompt arguments: {', '.join(missing)}")
        return template.template.format(**kwargs)

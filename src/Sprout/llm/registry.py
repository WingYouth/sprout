"""Named model provider registry with a default provider."""

from __future__ import annotations

from dataclasses import dataclass, field

from Sprout.llm.base import ModelProvider
from Sprout.registry.base import Registry


@dataclass(slots=True)
class ModelRegistry:
    _registry: Registry[ModelProvider] = field(default_factory=Registry)
    default_name: str = "echo"

    def register(self, provider: ModelProvider, *, default: bool = False) -> None:
        self._registry.register(provider.name, provider, replace=True)
        if default:
            self.default_name = provider.name

    def get(self, name: str) -> ModelProvider:
        return self._registry.get(name)

    def default(self) -> ModelProvider:
        return self._registry.get(self.default_name)

    def list(self) -> dict[str, ModelProvider]:
        return self._registry.list()

"""RuntimeInfo: the public self-description returned by ``Runtime.describe()``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    name: str
    version: str
    default_agent: str
    agents: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    model_providers: tuple[str, ...] = ()
    default_model: str = ""
    storage: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "default_agent": self.default_agent,
            "agents": list(self.agents),
            "tools": list(self.tools),
            "skills": list(self.skills),
            "model_providers": list(self.model_providers),
            "default_model": self.default_model,
            "storage": dict(self.storage),
        }

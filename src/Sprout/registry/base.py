"""Generic named-object registry shared by agents, tools, skills, and prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RegistryEntry[T]:
    value: T
    enabled: bool = True


class Registry[T]:
    """A name-keyed object registry with enable/disable semantics."""

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry[T]] = {}

    def register(self, name: str, value: T, *, replace: bool = False) -> None:
        if name in self._entries and not replace:
            raise ValueError(f"Registry entry already exists: {name}")
        self._entries[name] = RegistryEntry(value=value)

    def unregister(self, name: str) -> None:
        self._entries.pop(name, None)

    def get(self, name: str) -> T:
        entry = self._entries[name]
        if not entry.enabled:
            raise LookupError(f"Registry entry is disabled: {name}")
        return entry.value

    def contains(self, name: str, *, enabled_only: bool = True) -> bool:
        entry = self._entries.get(name)
        return entry is not None and (entry.enabled or not enabled_only)

    def list(self, *, enabled_only: bool = True) -> dict[str, T]:
        return {
            name: entry.value
            for name, entry in self._entries.items()
            if entry.enabled or not enabled_only
        }

    def enable(self, name: str) -> None:
        self._entries[name].enabled = True

    def disable(self, name: str) -> None:
        self._entries[name].enabled = False

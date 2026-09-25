"""In-memory cache store."""

from __future__ import annotations

from typing import Any


class MemoryCacheStore:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

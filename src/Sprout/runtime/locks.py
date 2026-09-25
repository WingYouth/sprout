"""Workspace-scoped async locks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class WorkspaceLockManager:
    """Serializes tasks that target the same workspace."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock(self, workspace_id: str):
        lock = self._locks.setdefault(workspace_id, asyncio.Lock())
        async with lock:
            yield

    def count(self) -> int:
        return len(self._locks)

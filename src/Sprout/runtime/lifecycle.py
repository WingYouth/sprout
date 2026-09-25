"""Runtime lifecycle helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from Sprout.runtime.runtime import Runtime


@asynccontextmanager
async def managed(runtime: Runtime) -> AsyncIterator[Runtime]:
    """Start a runtime on entry and always stop it on exit."""
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()

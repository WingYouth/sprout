"""Extension points for optional adapters (Weixin, browser, schedulers, ...)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("sprout.extensions")

ExtensionSetup = Callable[[Any], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class Extension:
    name: str
    setup: ExtensionSetup
    version: str = "0.1.0"
    description: str = ""


class ExtensionRegistry:
    """Registers optional extensions and notifies them at composition time."""

    def __init__(self) -> None:
        self._extensions: dict[str, Extension] = {}

    def register(self, extension: Extension, *, replace: bool = False) -> None:
        if extension.name in self._extensions and not replace:
            raise ValueError(f"Extension already registered: {extension.name}")
        self._extensions[extension.name] = extension

    def list(self) -> dict[str, Extension]:
        return dict(self._extensions)

    async def notify_ready(self, context: Any) -> None:
        """Invoke every setup callback; one failing extension never blocks startup."""
        for name, extension in self._extensions.items():
            try:
                result = extension.setup(context)
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:
                logger.exception("Extension %s failed during setup", name)

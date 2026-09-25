"""Skill store contract: the installed-skill registry (design §10.3).

This store is the authority behind ``.hub/index.json``. The JSON file stays as the
fast, human-readable snapshot the matcher and the L0 injection read (design §7.2);
the registry is the source of truth for what is installed, where it came from, and
whether it is trusted.

Runtime depends on this protocol, never on the SQLite implementation.
"""

from __future__ import annotations

from typing import Protocol

from Sprout.skills.models import SkillRecord


class SkillStore(Protocol):
    """Persists one :class:`SkillRecord` per installed skill (design §10)."""

    async def upsert(self, record: SkillRecord) -> None: ...
    async def get(self, name: str) -> SkillRecord | None: ...
    async def list(
        self,
        *,
        source: str | None = None,
        trust: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillRecord]: ...
    async def set_enabled(self, name: str, enabled: bool) -> None: ...
    async def set_trust(self, name: str, trust: str) -> None: ...
    async def remove(self, name: str) -> None: ...

    async def is_trusted(self, name: str, digest: str) -> bool:
        """True only when ``name`` is trusted *and* its content matches ``digest``."""
        ...

"""In-memory skill store for tests and ephemeral runtimes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from Sprout.skills.models import SkillRecord, TrustLevel


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MemorySkillStore:
    """Dict-backed :class:`~Sprout.storage.contracts.skills.SkillStore`."""

    def __init__(self) -> None:
        self.records: dict[str, SkillRecord] = {}

    async def upsert(self, record: SkillRecord) -> None:
        self.records[record.name] = record

    async def get(self, name: str) -> SkillRecord | None:
        return self.records.get(name)

    async def list(
        self,
        *,
        source: str | None = None,
        trust: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillRecord]:
        records = list(self.records.values())
        if source is not None:
            records = [record for record in records if record.source == source]
        if trust is not None:
            records = [record for record in records if record.trust == trust]
        if enabled_only:
            records = [record for record in records if record.enabled]
        return sorted(records, key=lambda record: record.name)

    async def set_enabled(self, name: str, enabled: bool) -> None:
        record = self.records.get(name)
        if record is not None:
            self.records[name] = replace(record, enabled=enabled, updated_at=_now())

    async def set_trust(self, name: str, trust: str) -> None:
        record = self.records.get(name)
        if record is not None:
            self.records[name] = replace(record, trust=trust, updated_at=_now())

    async def remove(self, name: str) -> None:
        self.records.pop(name, None)

    async def is_trusted(self, name: str, digest: str) -> bool:
        record = self.records.get(name)
        if record is None:
            return False
        return record.trust == TrustLevel.TRUSTED.value and record.digest == digest

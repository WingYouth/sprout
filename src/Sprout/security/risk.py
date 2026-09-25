"""Tool risk classification shared by specs, policies, and approvals."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @classmethod
    def coerce(cls, value: RiskLevel | str) -> RiskLevel:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().casefold()
        try:
            return cls(normalized)
        except ValueError:
            valid = ", ".join(level.value for level in cls)
            raise ValueError(f"Unknown risk level {value!r}; expected one of: {valid}") from None


_SEVERITY = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

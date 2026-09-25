"""Evidence references: every growth signal must point at observable data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A pointer to one piece of evidence (an event, turn, or knowledge item)."""

    source_type: str  # "event" | "turn" | "knowledge" | ...
    source_id: str
    note: str | None = None

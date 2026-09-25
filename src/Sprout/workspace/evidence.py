"""Evidence references for workspace graph and knowledge items."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_type: str = "file"
    path: str = ""
    line: int = 0
    revision: str = ""
    analyzer: str = ""
    confidence: float = 1.0
    id: str = field(default_factory=lambda: str(uuid4()))

    def display_id(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.source_type}:{location}:{self.analyzer}"


__all__ = ["EvidenceRef"]

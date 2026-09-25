"""Immutable event record published on the in-process event bus."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    """A named occurrence with an optional correlation id linking one online turn."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

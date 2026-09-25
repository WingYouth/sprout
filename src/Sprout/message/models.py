from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import uuid4


def _empty_metadata() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Message:
    content: str
    channel: str = "internal"
    user_id: str = "anonymous"
    session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    content: str
    channel: str
    session_id: str
    correlation_id: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One event from an online streaming turn."""

    content: str = ""
    outbound: OutboundMessage | None = None
    error: str | None = None

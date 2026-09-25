"""Attachments carried alongside unified messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file attached to a message, referenced by URI or carried inline."""

    filename: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    uri: str | None = None
    data: bytes | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

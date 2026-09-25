"""Session and turn domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class Session:
    """A control-conversation session (``sprout_conversation.db`` authority).

    The authority columns of ``guidance.md`` §19.2 (``channel``,
    ``target_ref_id``, ``title``, ``status``, ``locale``, ``summary``,
    ``updated_at``) are first-class fields so the CLI/gateway can render and
    filter sessions without unpacking ``metadata``. They are appended after the
    original fields so existing positional/keyword construction stays valid.
    """

    id: str
    user_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    channel: str = ""
    target_ref_id: str | None = None
    title: str = ""
    status: str = "active"
    locale: str = ""
    summary: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Turn:
    """One stored message within a session (``user`` or ``assistant``).

    ``seq`` is the per-session monotonic sequence assigned by the store on
    append; it is the only trustworthy ordering key (wall clocks lie).

    ``metadata`` is the message envelope (channel, user_id, message_id,
    correlation_id, blob references, agent result metadata...). It keeps the
    authority row lossless: a ``Message`` reconstructed from a stored turn
    carries everything the inbound/outbound message carried (see
    :mod:`Sprout.message.converter`). Roles stored here are evidence only —
    authorization never reads them back (AUTHZ §4).
    """

    session_id: str
    role: str
    content: str
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    seq: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    # --- Message authority columns (guidance.md §19.2) ---
    # Appended last so existing positional construction (e.g. the lanediag
    # probe) keeps working. ``content_type='folded_block'`` + ``line_count``
    # implement the CLI multi-line paste contract (§19.2 L694-697).
    content_type: str = "text"
    content_blob_uri: str | None = None
    line_count: int = 0
    token_estimate: int = 0
    language: str = ""

"""Wire-format conversion between unified messages and plain dictionaries.

This module also owns the **turn envelope** contract: the mapping between an
inbound/outbound :class:`Message` and the ``Turn.metadata`` persisted by the
session layer. It lives here (not in ``session.models``) so the rootstock
backends never import the message package — the dependency stays one-way.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from Sprout.message.attachment import Attachment
from Sprout.message.models import Message, OutboundMessage

if TYPE_CHECKING:
    from Sprout.session.models import Turn
    from Sprout.storage.contracts.blobs import BlobStore

#: Envelope keys that are copied back onto a reconstructed ``Message.metadata``.
_MESSAGE_METADATA_KEY = "message_metadata"

#: Marker set when a blob-backed body could not be resolved on read.
BLOB_UNRESOLVED = "blob_unresolved"


def attachment_to_dict(attachment: Attachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "size": attachment.size,
        "uri": attachment.uri,
    }


def attachment_from_dict(data: Mapping[str, Any]) -> Attachment:
    return Attachment(
        filename=data["filename"],
        mime_type=data.get("mime_type", "application/octet-stream"),
        size=int(data.get("size", 0)),
        uri=data.get("uri"),
        id=data.get("id") or str(uuid4()),
    )


def message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "content": message.content,
        "channel": message.channel,
        "user_id": message.user_id,
        "session_id": message.session_id,
        "metadata": dict(message.metadata),
        "created_at": message.created_at.isoformat(),
    }


def message_from_dict(data: Mapping[str, Any]) -> Message:
    created_at = data.get("created_at")
    return Message(
        content=data["content"],
        channel=data.get("channel", "internal"),
        user_id=data.get("user_id", "anonymous"),
        session_id=data.get("session_id"),
        metadata=dict(data.get("metadata") or {}),
        id=data.get("id") or str(uuid4()),
        created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(UTC),
    )


def outbound_to_dict(outbound: OutboundMessage) -> dict[str, Any]:
    return {
        "content": outbound.content,
        "channel": outbound.channel,
        "session_id": outbound.session_id,
        "correlation_id": outbound.correlation_id,
        "metadata": dict(outbound.metadata),
    }


# -- turn envelope contract -------------------------------------------------


def turn_envelope(message: Message) -> dict[str, Any]:
    """The envelope stored alongside a persisted ``user`` turn.

    Keeps the authority row lossless: channel, user, and the inbound message
    id survive the round trip into the session layer.
    """
    envelope: dict[str, Any] = {
        "channel": message.channel,
        "user_id": message.user_id,
        "message_id": message.id,
    }
    if message.metadata:
        envelope[_MESSAGE_METADATA_KEY] = dict(message.metadata)
    return envelope


def assistant_envelope(
    message: Message, result_metadata: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The envelope stored alongside a persisted ``assistant`` turn.

    ``correlation_id`` links the reply back to the inbound message id, and
    ``agent`` carries whatever the agent surfaced (steps, truncation flags,
    token usage...).
    """
    envelope: dict[str, Any] = {
        "channel": message.channel,
        "user_id": message.user_id,
        "message_id": message.id,
        "correlation_id": message.id,
    }
    if result_metadata:
        envelope["agent"] = dict(result_metadata)
    return envelope


async def message_from_turn(
    turn: Turn, *, blobs: BlobStore | None = None
) -> Message:
    """Reconstruct a Message from a stored turn (the P2 lossless-read check).

    ``user`` turns rebuild the original inbound message. ``assistant`` turns
    rebuild a message-shaped view with the reply semantics exposed through
    ``metadata`` (``role``/``correlation_id``/``agent``).

    When the envelope carries a ``blob_uri`` (oversized body offloaded by the
    runtime) and a ``blobs`` store is given, the full body is resolved back.
    Without a store — or on a resolution failure — the preview is returned and
    ``metadata["blob_unresolved"]`` marks the degradation instead of silently
    pretending the preview is the whole body.
    """
    envelope = dict(turn.metadata)
    content = turn.content
    blob_uri = envelope.get("blob_uri")
    if isinstance(blob_uri, str):
        if blobs is None:
            envelope[BLOB_UNRESOLVED] = True
        else:
            try:
                content = (await blobs.get(blob_uri)).decode(
                    "utf-8", errors="replace"
                )
            except Exception:  # noqa: BLE001 - read side degrades, never raises
                envelope[BLOB_UNRESOLVED] = True

    metadata = dict(envelope.get(_MESSAGE_METADATA_KEY) or {})
    metadata.pop("role", None)
    if turn.role != "user":
        metadata["role"] = turn.role
    for key in ("correlation_id", "agent", "blob_uri", "content_bytes"):
        if key in envelope:
            metadata[key] = envelope[key]

    return Message(
        content=content,
        channel=str(envelope.get("channel", "internal")),
        user_id=str(envelope.get("user_id", "anonymous")),
        session_id=turn.session_id,
        metadata=metadata,
        id=str(envelope.get("message_id") or turn.id),
        created_at=turn.created_at or datetime.now(UTC),
    )

"""Large-content offload: keep the hot rows thin, push the body to the blob store.

A ``Turn.content`` over :data:`OFFLOAD_THRESHOLD` (8 KiB by default) is replaced
with a short preview plus a ``blob://`` URI in the session layer. When a
summarizer or a fresh context wants the full text it can call
:func:`resolve_turn_body` to read it back, and a failed read is surfaced as
``[完整内容不可用]`` (C6).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from Sprout.session.models import Turn

if TYPE_CHECKING:
    from Sprout.storage.contracts.blobs import BlobStore

OFFLOAD_THRESHOLD = 8192
PREVIEW_CHARS = 500
UNREADABLE_MARKER = "[完整内容不可用]"


async def offload_turn(
    turn: Turn, blobs: BlobStore | None
) -> Turn:
    """Replace ``turn.content`` with preview + URI when it is too big to inline."""
    if blobs is None or len(turn.content.encode("utf-8")) <= OFFLOAD_THRESHOLD:
        return turn
    key = f"turns/{turn.session_id}/{turn.id}"
    await blobs.put(key, turn.content.encode("utf-8"))
    preview = _preview(turn.content)
    replaced = f"{preview}\n[blob://{key}]"
    return replace(turn, content=replaced)


def _preview(content: str) -> str:
    if len(content) <= PREVIEW_CHARS:
        return content
    return content[:PREVIEW_CHARS] + "…"


async def resolve_turn_body(
    turn: Turn,
    blobs: BlobStore | None,
) -> str:
    """Return the full body for an offloaded turn; mark unreadable on failure."""
    if blobs is None or "[blob://" not in turn.content:
        return turn.content
    key = turn.content.split("[blob://", 1)[1].split("]", 1)[0]
    try:
        body = await blobs.get(key)
    except (KeyError, OSError):
        return UNREADABLE_MARKER
    return body.decode("utf-8", errors="replace")


__all__ = ["offload_turn", "resolve_turn_body", "OFFLOAD_THRESHOLD", "UNREADABLE_MARKER"]
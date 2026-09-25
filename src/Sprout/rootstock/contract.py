"""Rootstock contract: the persistence interface every session backend implements.

Rootstock (砧木) is the root system a sprout is grafted onto: it stores and
feeds the session layer. Every backend — SQLite, JSONL, blobstore, Milvus,
Neo4j, Redis, or in-memory — implements :class:`SessionStore`, and the runtime
depends on this protocol only, never on a concrete database.

The protocol is intentionally a subset of ``OperationalStore`` so the
operational store remains a structural fallback when no dedicated session
backend is configured.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from Sprout.session.models import Session, Turn

#: Envelope key the runtime stores an offloaded body's URI under. The runtime
#: writes it here rather than into ``Turn.content_blob_uri``: the body is
#: offloaded by rewriting the *envelope* (``Runtime._offload_body``), and the
#: read side resolves it from the same place (``message.converter``).
BLOB_URI_ENVELOPE_KEY = "blob_uri"


def blob_uri_of(turn: Turn) -> str:
    """The blob URI a turn references, from the column *or* the envelope.

    Both are checked because they are written by different layers: the runtime's
    offload path records the envelope key, while ``content_blob_uri`` is the
    authority column's own slot. Reading only one of them silently leaks every
    body offloaded by the other, and a leak in a content-addressed store is
    permanent — there is no garbage collector to fall back on.
    """
    if turn.content_blob_uri:
        return turn.content_blob_uri
    envelope = turn.metadata.get(BLOB_URI_ENVELOPE_KEY) if turn.metadata else None
    return envelope if isinstance(envelope, str) and envelope else ""


def blob_uris_in(turns: Iterable[Turn]) -> list[str]:
    """Every blob URI a session's turns reference, de-duplicated, order kept."""
    seen: dict[str, None] = {}
    for turn in turns:
        uri = blob_uri_of(turn)
        if uri:
            seen.setdefault(uri, None)
    return list(seen)


#: ``Turn`` fields a document-store backend must round-trip *beside* the ones
#: the original seven-key shape carried. Kept as a tuple so the JSONL, blobstore
#: and any future document backend serialize the same set: they each used to
#: hand-roll a dict holding only id/session/role/content/created_at/seq/metadata,
#: which silently dropped every message-authority column the SQLite backend
#: keeps — a turn read back from those stores lost its ``content_type``,
#: ``line_count``, ``token_estimate``, ``language`` and ``content_blob_uri``.
TURN_AUTHORITY_FIELDS: tuple[tuple[str, Any], ...] = (
    ("content_type", "text"),
    ("content_blob_uri", None),
    ("line_count", 0),
    ("token_estimate", 0),
    ("language", ""),
)


def turn_to_document(turn: Turn) -> dict[str, Any]:
    """One turn as the JSON object a document store persists.

    The shared half of the three document backends' ``_turn_document``: they
    must agree, because a turn written by one and read by another has to come
    back whole.
    """
    document: dict[str, Any] = {
        "kind": "turn",
        "id": turn.id,
        "session_id": turn.session_id,
        "role": turn.role,
        "content": turn.content,
        "created_at": turn.created_at.isoformat(),
        "seq": turn.seq,
        "metadata": turn.metadata,
    }
    for name, _default in TURN_AUTHORITY_FIELDS:
        document[name] = getattr(turn, name)
    return document


def turn_from_document(document: Mapping[str, Any]) -> Turn:
    """The inverse of :func:`turn_to_document`, tolerant of older records.

    A document written before these fields existed simply lacks the keys, so
    each falls back to the dataclass default rather than raising — that is what
    keeps a pre-existing JSONL or blobstore file readable.
    """
    from datetime import datetime

    kwargs: dict[str, Any] = {
        "session_id": document["session_id"],
        "role": document["role"],
        "content": document["content"],
        "id": document["id"],
        "created_at": datetime.fromisoformat(document["created_at"]),
        "seq": int(document.get("seq", 0)),
        "metadata": document.get("metadata") or {},
    }
    for name, default in TURN_AUTHORITY_FIELDS:
        kwargs[name] = document.get(name, default)
    return Turn(**kwargs)


class SessionStore(Protocol):
    """Persistence boundary for sessions and their turns."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def save_session(self, session: Session) -> None: ...

    async def append_turn(self, turn: Turn) -> None: ...

    async def recent_turns(
        self, session_id: str, limit: int = 20
    ) -> Sequence[Turn]: ...

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> Sequence[Turn]:
        """Return turns older than ``seq``; keyset paging for the compactor."""
        ...

    async def delete_session(self, session_id: str) -> int:
        """Drop the session and every turn; returns the number of turns dropped."""
        ...

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference, for cascade cleanup.

        Part of the contract, not an optional extra. Blob URIs are
        content-addressed (a bare hash name with no session component), so the
        turns are the only record of which blob belongs to which session — a
        backend that cannot answer this makes every offloaded body it holds
        unreclaimable. ``StorageBundle.delete_session_cascade`` probes for the
        method and treats absence as "no blobs", so a missing implementation
        leaks silently rather than failing loudly.
        """
        ...

    async def count_sessions(self) -> int: ...

    async def count_turns(self) -> int: ...

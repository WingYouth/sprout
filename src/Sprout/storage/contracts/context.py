"""Context store contract: what the model actually saw, per turn.

A :class:`ContextRecord` is the frozen composition result — the rendered
memory block, the working window size, the snapshot hash — persisted so a
past answer can be replayed and audited ("why did the model say that?").
The authority for context snapshots is one durable store (SQLite table or
JSONL log, picked by DSN); the six-lane fan-out additionally mirrors each
record into the derived lanes (Redis hot copy, Milvus snapshot embedding,
Neo4j projection, blobstore for oversized bodies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ContextRecord:
    """One persisted context composition for a session at a turn boundary."""

    session_id: str
    snapshot_hash: str
    text: str
    turn_seq: int = 0
    token_estimate: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Blobstore URI when the oversized body was written out-of-line.
    blob_uri: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "snapshot_hash": self.snapshot_hash,
            "text": self.text,
            "turn_seq": self.turn_seq,
            "token_estimate": self.token_estimate,
            "created_at": self.created_at.isoformat(),
            "blob_uri": self.blob_uri,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> ContextRecord:
        return cls(
            session_id=str(data["session_id"]),
            snapshot_hash=str(data["snapshot_hash"]),
            text=str(data["text"]),
            turn_seq=int(data.get("turn_seq") or 0),
            token_estimate=int(data.get("token_estimate") or 0),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            blob_uri=data.get("blob_uri"),  # type: ignore[arg-type]
        )


class ContextStore(Protocol):
    """Durable, append-only log of context compositions."""

    async def append(self, record: ContextRecord) -> None: ...

    async def latest(self, session_id: str) -> ContextRecord | None: ...

    async def list_records(
        self, session_id: str, *, limit: int = 20
    ) -> list[ContextRecord]: ...

    async def search(self, query: str, *, limit: int = 10) -> list[ContextRecord]: ...

    async def count(self) -> int: ...


__all__ = ["ContextRecord", "ContextStore"]

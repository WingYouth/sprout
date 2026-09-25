"""Vector store contract.

Vectors are namespaced so the same backend can serve multiple layers (knowledge
chunks, session turns, skills) without cross-talk. :class:`VectorStore` is the
runtime interface every backend implements; the namespace constants are the
only canonical names used across backends.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# Canonical namespace identifiers. Backends must route on them exactly so the
# in-memory store, Milvus collection, and any future lane stay aligned.
MESSAGES = "messages"
SESSION_TURNS = MESSAGES  # backwards-compatible alias
KNOWLEDGE_CHUNKS = "knowledge_chunks"
SKILLS = "skills"


@dataclass(frozen=True, slots=True)
class VectorHit:
    """One search result: the stored vector's key, its score, and namespace."""

    key: str
    score: float
    namespace: str = SESSION_TURNS
    metadata: Mapping[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    """Async vector store keyed by ``key`` within a ``namespace``."""

    async def upsert(
        self,
        key: str,
        vector: Sequence[float],
        *,
        namespace: str = SESSION_TURNS,
        metadata: Mapping[str, Any] | None = None,
    ) -> None: ...

    async def search(
        self,
        vector: Sequence[float],
        limit: int = 5,
        *,
        namespace: str = SESSION_TURNS,
        filters: Mapping[str, Any] | None = None,
    ) -> Sequence[VectorHit]: ...

    async def delete(self, key: str, *, namespace: str = SESSION_TURNS) -> bool: ...

    async def count(self, *, namespace: str | None = None) -> int: ...

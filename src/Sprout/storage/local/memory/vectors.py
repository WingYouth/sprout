"""In-process vector store: the default backend and Milvus fallback.

Keeps embeddings in memory and ranks by cosine similarity. No external service,
no embedding model — vectors are handed in by the caller — so the vector layer
works offline and degrades gracefully when Milvus is absent.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from Sprout.storage.contracts.vectors import SESSION_TURNS, VectorHit


@dataclass(slots=True)
class _Entry:
    vector: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when lengths differ or either side is zero."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class MemoryVectorStore:
    """Namespaced vectors in process memory, searched by cosine similarity."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, _Entry]] = {}

    def _bucket(self, namespace: str) -> dict[str, _Entry]:
        return self._namespaces.setdefault(namespace, {})

    async def upsert(
        self,
        key: str,
        vector: Sequence[float],
        *,
        namespace: str = SESSION_TURNS,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._bucket(namespace)[key] = _Entry(
            vector=tuple(float(value) for value in vector),
            metadata=dict(metadata or {}),
        )

    async def search(
        self,
        vector: Sequence[float],
        limit: int = 5,
        *,
        namespace: str = SESSION_TURNS,
        filters: Mapping[str, Any] | None = None,
    ) -> Sequence[VectorHit]:
        wanted = dict(filters or {})
        hits: list[VectorHit] = []
        for key, entry in self._bucket(namespace).items():
            if any(entry.metadata.get(name) != value for name, value in wanted.items()):
                continue
            hits.append(
                VectorHit(
                    key=key,
                    score=_cosine(vector, entry.vector),
                    namespace=namespace,
                    metadata=dict(entry.metadata),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.key))
        return hits[:limit]

    async def delete(self, key: str, *, namespace: str = SESSION_TURNS) -> bool:
        return self._bucket(namespace).pop(key, None) is not None

    async def count(self, *, namespace: str | None = None) -> int:
        if namespace is None:
            return sum(len(bucket) for bucket in self._namespaces.values())
        return len(self._bucket(namespace))

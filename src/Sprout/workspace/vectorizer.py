"""Deterministic offline text vectorizer for local knowledge indexing."""

from __future__ import annotations

import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class HashVectorizer:
    """Hash tokens into a fixed-size vector without an embedding model."""

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self._dimensions
        tokens = _TOKEN_RE.findall(text.casefold())
        for token in tokens:
            bucket = self._bucket(token)
            sign = 1.0 if bucket % 2 == 0 else -1.0
            vector[bucket] += sign
        for token in tokens:
            for index in range(max(0, len(token) - 1)):
                bigram = token[index : index + 2]
                bucket = self._bucket(f"~{bigram}")
                vector[bucket] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def _bucket(self, token: str) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        return value % self._dimensions


__all__ = ["HashVectorizer"]

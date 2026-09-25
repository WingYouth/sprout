"""Deterministic offline embeddings for the vector lanes.

Real semantic recall wants a model API, but the storage lanes must work — and
be testable — with no network and no API key. :class:`HashingEmbedder` is the
default: word unigrams plus character trigrams are feature-hashed into a
fixed-width vector and L2-normalized, so the same text always embeds to the
same vector, similar texts land close, and the output dimension matches the
Milvus collection schema. Swap in an API-backed embedder by passing any
callable ``(text: str) -> list[float]`` where an embedder is accepted.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable

Embedder = Callable[[str], "list[float]"]

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _signed_hash(token: str, salt: int) -> tuple[int, float]:
    digest = hashlib.md5(f"{salt}:{token}".encode()).digest()
    value = int.from_bytes(digest[:4], "big")
    sign = -1.0 if digest[4] & 1 else 1.0
    return value, sign


class HashingEmbedder:
    """Feature-hashing embedder: deterministic, dependency-free, fixed-width.

    Tokens are lowercased word unigrams and character trigrams. Each token is
    hashed into one bucket with a +-1 sign (the hashing-trick), accumulated,
    and the final vector is L2-normalized so cosine and inner product agree.
    """

    def __init__(self, dim: int = 1536) -> None:
        if dim <= 0:
            raise ValueError(f"Embedding dimension must be positive, got {dim}")
        self.dim = dim

    def __call__(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        if not text:
            return vector
        words = _TOKEN_RE.findall(text.lower())
        tokens: list[str] = list(words)
        for word in words:
            padded = f"  {word} "
            tokens.extend(padded[i : i + 3] for i in range(len(padded) - 2))
        for token in tokens:
            index, sign = _signed_hash(token, 0)
            vector[index % self.dim] += sign
        norm = math.sqrt(sum(component * component for component in vector))
        if norm > 0.0:
            vector = [component / norm for component in vector]
        return vector


class ApiEmbedder:
    """OpenAI-compatible embeddings endpoint with an offline hashing fallback.

    The vector lanes must keep working without network or an API key, so an
    unconfigured or failed API call degrades to :class:`HashingEmbedder` at the
    same width instead of raising. Configure via ``EMBEDDING_BASE_URL``,
    ``EMBEDDING_MODEL``, ``EMBEDDING_API_KEY`` and ``EMBEDDING_DIM``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        dim: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self.dim = dim
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._api_key = api_key.strip()
        self._timeout = timeout
        self._fallback = HashingEmbedder(dim)

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._model and self._api_key)

    async def embed(self, text: str) -> list[float]:
        if not self.configured:
            return self._fallback(text)
        import httpx

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            ) as client:
                response = await client.post(
                    "/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": text},
                )
                response.raise_for_status()
                data = response.json()
            return list(data["data"][0]["embedding"])
        except Exception:  # noqa: BLE001 - the offline fallback must never fail
            return self._fallback(text)


def make_embedder() -> ApiEmbedder:
    """Build the configured embedder, defaulting to offline hashing."""
    return ApiEmbedder(
        base_url=os.environ.get("EMBEDDING_BASE_URL", ""),
        model=os.environ.get("EMBEDDING_MODEL", ""),
        api_key=os.environ.get("EMBEDDING_API_KEY", ""),
        dim=int(os.environ.get("EMBEDDING_DIM", "1536")),
    )


__all__ = ["ApiEmbedder", "Embedder", "HashingEmbedder", "make_embedder"]

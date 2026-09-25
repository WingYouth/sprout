"""In-memory blob store for tests and ephemeral runtimes."""

from __future__ import annotations

from typing import Self


class MemoryBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, data: bytes, *, mime_type: str) -> str:
        uri = f"memory://{len(self.blobs)}-{mime_type.replace('/', '-')}"
        self.blobs[uri] = data
        return uri

    async def get(self, uri: str) -> bytes:
        return self.blobs[uri]

    async def exists(self, uri: str) -> bool:
        return uri in self.blobs

    async def delete(self, uri: str) -> bool:
        return self.blobs.pop(uri, None) is not None

    async def count(self) -> int:
        return len(self.blobs)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.blobs.clear()

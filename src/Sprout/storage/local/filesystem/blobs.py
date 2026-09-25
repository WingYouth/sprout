"""Filesystem blob store (media/ directory, content-addressed)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/html": ".html",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "audio/mpeg": ".mp3",
    "video/mp4": ".mp4",
}


class FileBlobStore:
    """Stores blobs under ``root`` named by content hash; URIs are file names."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, uri: str) -> Path:
        name = uri.removeprefix("file://").replace("..", "_").lstrip("/\\")
        return self._root / name

    async def put(self, data: bytes, *, mime_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        extension = _MIME_EXTENSIONS.get(mime_type, ".bin")
        name = f"{digest}{extension}"
        path = self._root / name
        if not path.exists():
            await asyncio.to_thread(path.write_bytes, data)
        return name

    async def get(self, uri: str) -> bytes:
        return await asyncio.to_thread(self._path_for(uri).read_bytes)

    async def exists(self, uri: str) -> bool:
        return self._path_for(uri).exists()

    async def delete(self, uri: str) -> bool:
        path = self._path_for(uri)
        if path.exists():
            path.unlink()
            return True
        return False

    async def count(self) -> int:
        return sum(1 for _ in self._root.iterdir() if _.is_file())

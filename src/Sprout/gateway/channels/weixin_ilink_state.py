"""Persistent Weixin iLink per-peer routing state."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("sprout.gateway.weixin_ilink.state")

_ACCOUNT_KEY = "@account"


class _JsonStateStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read Weixin iLink state file: %s", self._path)
            return None
        return data if isinstance(data, dict) else None

    def save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)


class WeixinIlinkStateStore:
    """Persist context tokens, session ids, and last task ids per peer."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        legacy_context_path: str | Path | None = None,
    ) -> None:
        self._store = _JsonStateStore(path) if path is not None else None
        self._states: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

        loaded = self._store.load() if self._store is not None else None
        if loaded:
            self._load_new_format(loaded)
        elif legacy_context_path is not None:
            legacy = _JsonStateStore(legacy_context_path).load()
            if legacy:
                self._load_legacy_tokens(legacy)

    async def get_context_token(self, peer_user_id: str) -> str:
        async with self._lock:
            return self._peer(peer_user_id).get("context_token", "")

    async def set_context_token(self, peer_user_id: str, token: str) -> None:
        async with self._lock:
            if token:
                self._peer(peer_user_id)["context_token"] = token
            else:
                self._peer(peer_user_id).pop("context_token", None)
            self._persist()

    async def clear_context_token(self, peer_user_id: str) -> None:
        await self.set_context_token(peer_user_id, "")

    async def get_session_id(self, peer_user_id: str) -> str:
        async with self._lock:
            return self._peer(peer_user_id).get("session_id", "")

    async def set_session_id(self, peer_user_id: str, session_id: str) -> None:
        async with self._lock:
            if session_id:
                self._peer(peer_user_id)["session_id"] = session_id
            else:
                self._peer(peer_user_id).pop("session_id", None)
            self._persist()

    async def get_last_task_id(self, peer_user_id: str) -> str:
        async with self._lock:
            return self._peer(peer_user_id).get("last_task_id", "")

    async def set_last_task_id(self, peer_user_id: str, task_id: str) -> None:
        async with self._lock:
            if task_id:
                self._peer(peer_user_id)["last_task_id"] = task_id
            else:
                self._peer(peer_user_id).pop("last_task_id", None)
            self._persist()

    async def get_sync_buf(self) -> str:
        async with self._lock:
            return self._peer(_ACCOUNT_KEY).get("sync_buf", "")

    async def set_sync_buf(self, sync_buf: str) -> None:
        async with self._lock:
            if sync_buf:
                self._peer(_ACCOUNT_KEY)["sync_buf"] = sync_buf
            else:
                self._peer(_ACCOUNT_KEY).pop("sync_buf", None)
            self._persist()

    def _peer(self, peer_user_id: str) -> dict[str, str]:
        return self._states.setdefault(peer_user_id, {})

    def _load_new_format(self, data: dict[str, Any]) -> None:
        for peer, value in data.items():
            if isinstance(value, dict):
                self._states[str(peer)] = {
                    str(key): str(item)
                    for key, item in value.items()
                    if item is not None
                }
            elif value:
                self._states[str(peer)] = {"context_token": str(value)}

    def _load_legacy_tokens(self, data: dict[str, Any]) -> None:
        for peer, value in data.items():
            if value:
                self._states[str(peer)] = {"context_token": str(value)}

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(self._states)


__all__ = ["WeixinIlinkStateStore"]

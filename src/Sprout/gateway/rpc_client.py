"""Thin Python RPC client for external CLI and business applications."""

from __future__ import annotations

from typing import Any

import httpx


class RPCClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._token = token

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
        ) as client:
            headers = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            response = await client.post(
                "/api/rpc",
                json={
                    "id": "rpc-1",
                    "method": method,
                    "params": params or {},
                },
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

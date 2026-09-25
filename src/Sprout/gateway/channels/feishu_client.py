"""Feishu Open Platform HTTP client."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


class FeishuClient:
    """Minimal Feishu client for token acquisition and message sending."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.feishu.cn",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def send_text(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: str = "open_id",
    ) -> dict[str, Any]:
        token = await self._get_token()
        content = json.dumps({"text": text}, ensure_ascii=False)
        return await self._request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": content,
            },
            token=token,
        )

    async def get_tenant_access_token(self) -> str:
        """Acquire the tenant access token; useful for connectivity checks."""
        return await self._get_token()

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        data = await self._request(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self._app_id,
                "app_secret": self._app_secret,
            },
        )
        self._token = str(data["tenant_access_token"])
        self._token_expires_at = time.time() + int(data.get("expire", 7200))
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            transport=self._transport,
        ) as client:
            response = await client.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

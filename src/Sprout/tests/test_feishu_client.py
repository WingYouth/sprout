"""Tests for the Feishu Open Platform client."""

from __future__ import annotations

import asyncio

import httpx

from Sprout.gateway.channels.feishu_client import FeishuClient


def test_feishu_client_sends_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "token-1",
                    "expire": 7200,
                },
            )
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_1"}})

    async def run() -> None:
        client = FeishuClient(
            app_id="cli_test",
            app_secret="secret",
            transport=httpx.MockTransport(handler),
        )
        result = await client.send_text("ou_1", "hello")
        assert result["data"]["message_id"] == "om_1"

    asyncio.run(run())

"""Tests for the WeChat Dialog Open Platform adapter."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx

from Sprout.config.loader import default_settings
from Sprout.gateway.channels.wechat_dialog import (
    SqliteDedupStore,
    WeChatDialogClient,
    WeChatDialogGateway,
)
from Sprout.runtime.factory import create_runtime
from Sprout.storage.local.sqlite.driver import SqliteDatabase

_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")


def _callback_xml() -> str:
    return (
        "<xml>"
        "<userid>user-1</userid>"
        "<appid>wx-app</appid>"
        "<content><msg>explain this project</msg></content>"
        "<from>0</from>"
        "<channel>0</channel>"
        "<kfstate>0</kfstate>"
        "<assessment>0</assessment>"
        "</xml>"
    )


def test_client_encrypts_and_decrypts_message() -> None:
    client = WeChatDialogClient(
        token="token-1",
        encoding_aes_key=_KEY,
        appid="wx-app",
    )
    plaintext = _callback_xml()
    encrypted = client.encrypt_message(plaintext)
    assert client.decrypt_message(encrypted) == plaintext


def test_client_sends_encrypted_customer_service_message() -> None:
    client = WeChatDialogClient(
        token="token-1",
        encoding_aes_key=_KEY,
        appid="wx-app",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openapi/sendmsg/token-1"
        payload = json.loads(request.content)
        plaintext = client.decrypt_message(payload["encrypt"])
        assert "<openid>user-1</openid>" in plaintext
        assert "<msg>hello</msg>" in plaintext
        return httpx.Response(200, json={"errcode": 0, "msg": "成功"})

    async def run() -> None:
        client_with_transport = WeChatDialogClient(
            token="token-1",
            encoding_aes_key=_KEY,
            appid="wx-app",
            transport=httpx.MockTransport(handler),
        )
        result = await client_with_transport.send_message("user-1", "hello", 0)
        assert result["errcode"] == 0

    asyncio.run(run())


def test_gateway_callback_executes_task_and_sends_reply(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'metadata.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "trajectory")
    settings.storage.blobs_dir = str(tmp_path / "blobs")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "msg": "成功"})

    async def run() -> None:
        runtime = create_runtime(settings)
        workspace = await runtime.open_workspace(tmp_path)
        client = WeChatDialogClient(
            token="token-1",
            encoding_aes_key=_KEY,
            appid="wx-app",
            transport=httpx.MockTransport(handler),
        )
        gateway = WeChatDialogGateway(
            runtime,
            client=client,
            default_workspace_id=workspace.id,
            default_channel=0,
            default_appid="wx-app",
        )
        encrypted = client.encrypt_message(_callback_xml())
        result = await gateway.handle_callback({"encrypted": encrypted})
        assert result["ok"] is True
        assert result["task_id"]
        assert result["send_result"]["errcode"] == 0
        await runtime.stop()

    asyncio.run(run())


def test_gateway_ack_callback_deduplicates_retries() -> None:
    async def run() -> None:
        client = WeChatDialogClient(
            token="token-1",
            encoding_aes_key=_KEY,
            appid="wx-app",
        )
        gateway = WeChatDialogGateway(
            object(),
            client=client,
            dedup_window_seconds=60,
        )
        encrypted = client.encrypt_message(_callback_xml())
        result, event = await gateway.ack_callback({"encrypted": encrypted})
        assert result["queued"] is True
        assert event is not None

        duplicate, event = await gateway.ack_callback({"encrypted": encrypted})
        assert duplicate["ignored"] == "duplicate"
        assert event is None

    asyncio.run(run())


def test_sqlite_dedup_store_is_durable() -> None:
    async def run() -> None:
        store = SqliteDedupStore(SqliteDatabase(":memory:"))
        assert await store.acquire("key-1", ttl_seconds=10) is True
        assert await store.acquire("key-1", ttl_seconds=10) is False
        await store.release("key-1")
        assert await store.acquire("key-1", ttl_seconds=10) is True

    asyncio.run(run())


def test_gateway_resolves_workspace_by_channel() -> None:
    client = WeChatDialogClient(
        token="token-1",
        encoding_aes_key=_KEY,
        appid="wx-app",
    )
    gateway = WeChatDialogGateway(
        object(),
        client=client,
        default_workspace_id="ws-default",
        workspace_by_channel={"0": "ws-channel-0"},
    )
    event = gateway.parse_event(_callback_xml())
    assert gateway._resolve_workspace(event) == "ws-channel-0"

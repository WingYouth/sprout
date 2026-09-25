"""Tests for the Weixin iLink personal-WeChat gateway adapter."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx

from Sprout.gateway.channels.weixin_ilink import (
    WeixinIlinkAccount,
    WeixinIlinkAccountStore,
    WeixinIlinkClient,
    WeixinIlinkGateway,
    WeixinIlinkInbound,
)
from Sprout.message.models import OutboundMessage
from Sprout.task.models import Task, TaskResult, TaskStatus


class _FakeResult:
    task_id = "task-1"
    status = SimpleNamespace(value="completed")
    content = "hello from SEMA"
    metrics: dict = {}


class _TaskRuntime:
    def __init__(self) -> None:
        self.created_tasks = []

    async def create_task(
        self,
        workspace_id,
        instruction,
        *,
        actor=None,
        source="",
        delegation_scope=None,
        budget=None,
        message_id=None,
    ):
        task = Task(
            id="task-1",
            workspace_id=workspace_id,
            instruction=instruction,
            actor=actor,
            source=source,
            delegation_scope=delegation_scope,
        )
        self.created_tasks.append(task)
        return task

    async def execute(self, task):
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            content="task reply",
        )


class _ConversationRuntime:
    def __init__(self) -> None:
        self.messages = []

    async def handle(self, message):
        self.messages.append(message)
        return OutboundMessage(
            content="hello from SEMA",
            channel=message.channel,
            session_id=message.session_id or "sess-1",
            correlation_id=message.id,
        )


def _text_message() -> dict:
    return {
        "msg_type": 1,
        "from_user_id": "user-1",
        "to_user_id": "bot-1",
        "client_id": "client-1",
        "context_token": "ctx-1",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    }


def test_client_uses_ilink_headers_and_base_info() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ilink/bot/getupdates"
        assert request.headers["AuthorizationType"] == "ilink_bot_token"
        assert request.headers["iLink-App-Id"] == "bot"
        assert request.headers["iLink-App-ClientVersion"] == str((2 << 16) | (2 << 8) | 0)
        assert request.headers["Authorization"] == "Bearer token-1"
        payload = json.loads(request.content)
        assert payload["base_info"]["channel_version"] == "2.2.0"
        assert payload["get_updates_buf"] == "sync-1"
        return httpx.Response(200, json={"ret": 0, "msgs": [], "get_updates_buf": "sync-1"})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        result = await client.get_updates("sync-1")
        assert result["ret"] == 0

    asyncio.run(run())


def test_client_requests_qr_and_parses_login_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ilink/bot/get_bot_qrcode":
            assert request.method == "GET"
            assert request.url.params["bot_type"] == "3"
            return httpx.Response(
                200,
                json={"ret": 0, "qrcode": "qr-1", "qrcode_img_content": "https://qr"},
            )
        assert request.url.path == "/ilink/bot/get_qrcode_status"
        assert request.method == "GET"
        assert request.url.params["qrcode"] == "qr-1"
        return httpx.Response(
            200,
            json={
                "ret": 0,
                "status": "confirmed",
                "bot_token": "login-token",
                "ilink_bot_id": "bot-1",
                "baseurl": "https://ilinkai.weixin.qq.com",
                "ilink_user_id": "owner-1",
            },
        )

    async def run() -> None:
        client = WeixinIlinkClient(transport=httpx.MockTransport(handler))
        qr = await client.request_qr()
        assert qr["qrcode"] == "qr-1"
        status = await client.poll_qr_status(qr["qrcode"])
        account = WeixinIlinkAccount.from_payload(status)
        assert account.token == "login-token"
        assert account.account_id == "bot-1"

    asyncio.run(run())


def test_client_sends_bot_text_message() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ret": 0})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        await client.send_text("user-1", "hello", context_token="ctx-1")

    asyncio.run(run())
    msg = captured["payload"]["msg"]
    assert msg["to_user_id"] == "user-1"
    assert msg["context_token"] == "ctx-1"
    assert msg["message_type"] == 2
    assert msg["item_list"][0]["text_item"]["text"] == "hello"


def test_gateway_handles_dm_and_sends_reply() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ret": 0})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        account = WeixinIlinkAccount(token="token-1", account_id="bot-1")
        runtime = _ConversationRuntime()
        gateway = WeixinIlinkGateway(
            runtime,
            client=client,
            account=account,
            dm_policy="open",
        )
        inbound = WeixinIlinkInbound(
            from_user_id="user-1",
            text="hello",
            message_id="client-1",
            context_token="ctx-1",
        )
        result = await gateway.handle_inbound(inbound)
        assert result["ok"] is True
        assert result["task_id"] == ""
        assert result["session_id"] == "sess-1"
        assert captured["payload"]["msg"]["to_user_id"] == "user-1"
        assert captured["payload"]["msg"]["context_token"] == "ctx-1"

    asyncio.run(run())


def test_gateway_deduplicates_redelivered_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ret": 0})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        gateway = WeixinIlinkGateway(
            _ConversationRuntime(),
            client=client,
            account=WeixinIlinkAccount(token="token-1", account_id="bot-1"),
            dm_policy="open",
        )
        inbound = WeixinIlinkInbound(
            from_user_id="user-1",
            text="hello",
            message_id="client-1",
        )
        first = await gateway.handle_inbound(inbound)
        second = await gateway.handle_inbound(inbound)
        assert first["ok"] is True
        assert second["ignored"] == "duplicate"

    asyncio.run(run())


def test_gateway_skips_group_messages() -> None:
    gateway = WeixinIlinkGateway(
        _ConversationRuntime(),
        client=WeixinIlinkClient(token="token-1"),
        account=WeixinIlinkAccount(token="token-1", account_id="bot-1"),
    )
    message = _text_message()
    message["room_id"] = "room-1"
    assert gateway.parse_updates({"msgs": [message]}) == []


def test_gateway_task_prefix_uses_project_execution() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ret": 0})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        gateway = WeixinIlinkGateway(
            _TaskRuntime(),
            client=client,
            account=WeixinIlinkAccount(token="token-1", account_id="bot-1"),
            default_workspace_id="workspace-1",
            dm_policy="open",
        )
        result = await gateway.handle_inbound(
            WeixinIlinkInbound(
                from_user_id="user-1",
                text="/task explain this project",
                message_id="client-task",
                context_token="ctx-1",
            )
        )
        await asyncio.sleep(0)
        assert result["ok"] is True
        assert result["task_id"] == "task-1"
        assert captured["payload"]["msg"]["to_user_id"] == "user-1"
        assert captured["payload"]["msg"]["item_list"][0]["text_item"]["text"] == "task reply"

    asyncio.run(run())


def test_gateway_reuses_conversation_session() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ret": 0})

    async def run() -> None:
        client = WeixinIlinkClient(
            token="token-1",
            transport=httpx.MockTransport(handler),
        )
        runtime = _ConversationRuntime()
        gateway = WeixinIlinkGateway(
            runtime,
            client=client,
            account=WeixinIlinkAccount(token="token-1", account_id="bot-1"),
            dm_policy="open",
        )
        await gateway.handle_inbound(
            WeixinIlinkInbound(
                from_user_id="user-1",
                text="hello",
                message_id="client-1",
            )
        )
        await gateway.handle_inbound(
            WeixinIlinkInbound(
                from_user_id="user-1",
                text="hello again",
                message_id="client-2",
            )
        )
        assert runtime.messages[-1].session_id == "sess-1"

    asyncio.run(run())


def test_account_store_round_trips_credentials(tmp_path) -> None:
    store = WeixinIlinkAccountStore(tmp_path)
    store.save(
        WeixinIlinkAccount(
            token="secret-token",
            account_id="bot-1",
            user_id="owner-1",
        )
    )
    loaded = store.load()
    assert loaded is not None
    assert loaded.token == "secret-token"
    assert loaded.account_id == "bot-1"

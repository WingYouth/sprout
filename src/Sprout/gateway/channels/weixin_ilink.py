"""Weixin iLink personal-WeChat gateway adapter.

This channel follows Tencent's iLink Bot protocol rather than the WeChat
Dialog Open Platform webhook flow.  It uses QR login plus long-poll
``getupdates``, so no public callback URL, webhook, or ngrok tunnel is needed.

The existing :mod:`Sprout.gateway.channels.wechat_dialog` remains unchanged
and serves the separate customer-service callback protocol.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from Sprout.gateway.channels.weixin_ilink_router import WeixinIlinkRouter
from Sprout.gateway.channels.weixin_ilink_state import WeixinIlinkStateStore
from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.message.models import Message
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import DelegationScope, Task, TaskResult, TaskStatus

logger = logging.getLogger("sprout.gateway.weixin_ilink")

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_ID = "bot"
CLIENT_VERSION_INT = (2 << 16) | (2 << 8) | 0

LONG_POLL_TIMEOUT = 35.0
API_TIMEOUT = 15.0
QR_TIMEOUT = 35.0

_MESSAGE_TYPE_USER = 1
_MESSAGE_TYPE_BOT = 2
_MESSAGE_STATE_FINISH = 2
_ITEM_TYPE_TEXT = 1


@dataclass(slots=True)
class WeixinIlinkAccount:
    token: str
    account_id: str = ""
    base_url: str = DEFAULT_BASE_URL
    user_id: str = ""
    bot_type: str = "bot"

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_base_url: str = DEFAULT_BASE_URL,
        bot_type: str = "bot",
    ) -> WeixinIlinkAccount:
        token = _first_str(payload, "bot_token", "token", "access_token")
        if not token:
            raise ValueError("iLink login response did not contain bot_token")
        return cls(
            token=token,
            account_id=_first_str(
                payload,
                "ilink_bot_id",
                "account_id",
                "bot_id",
                "uin",
            ),
            base_url=_first_str(payload, "baseurl", "base_url") or fallback_base_url,
            user_id=_first_str(payload, "ilink_user_id", "user_id", "self_user_id"),
            bot_type=bot_type,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "token": self.token,
            "account_id": self.account_id,
            "base_url": self.base_url,
            "user_id": self.user_id,
            "bot_type": self.bot_type,
        }


@dataclass(slots=True)
class WeixinIlinkInbound:
    from_user_id: str
    text: str
    message_id: str
    context_token: str = ""


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _random_wechat_uin() -> str:
    value = secrets.randbelow(2**32)
    return base64.b64encode(str(value).encode("ascii")).decode("ascii")


def _first_str(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            return str(value)
    return ""


def _first_int(data: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


class WeixinIlinkClient:
    """Small async HTTP client for Tencent's iLink Bot endpoints."""

    def __init__(
        self,
        *,
        token: str = "",
        base_url: str = DEFAULT_BASE_URL,
        channel_version: str = CHANNEL_VERSION,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._channel_version = channel_version
        self._transport = transport

    async def request_qr(self, *, bot_type: str = "3") -> dict[str, Any]:
        return await self._get(
            "/ilink/bot/get_bot_qrcode",
            params={"bot_type": bot_type},
            timeout=QR_TIMEOUT,
        )

    async def poll_qr_status(
        self,
        qrcode: str,
    ) -> dict[str, Any]:
        return await self._get(
            "/ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            timeout=QR_TIMEOUT,
        )

    async def get_updates(self, sync_buf: str = "") -> dict[str, Any]:
        return await self._post(
            "/ilink/bot/getupdates",
            {"get_updates_buf": sync_buf},
            timeout=LONG_POLL_TIMEOUT,
        )

    async def send_text(
        self,
        to_user_id: str,
        text: str,
        *,
        context_token: str = "",
        client_id: str | None = None,
    ) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id or self._new_client_id(),
            "message_type": _MESSAGE_TYPE_BOT,
            "message_state": _MESSAGE_STATE_FINISH,
            "item_list": [
                {"type": _ITEM_TYPE_TEXT, "text_item": {"text": text}},
            ],
            "context_token": context_token,
        }
        return await self._post(
            "/ilink/bot/sendmessage",
            {"msg": msg},
            timeout=API_TIMEOUT,
        )

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        body_payload = {"base_info": self._base_info(), **payload}
        content = _json_bytes(body_payload)
        headers = self._build_headers(content)
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=self._transport,
        ) as client:
            response = await client.post(path, content=content, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("iLink API returned a non-object response")
        return data

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        headers = self._build_headers(b"")
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=self._transport,
        ) as client:
            response = await client.get(path, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("iLink API returned a non-object response")
        return data

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": self._channel_version}

    def _build_headers(self, content: bytes) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _random_wechat_uin(),
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(CLIENT_VERSION_INT),
            "Content-Length": str(len(content)),
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _new_client_id() -> str:
        return f"sema-{secrets.token_hex(16)}"


class JsonFileStore:
    """Minimal atomic JSON file store for iLink runtime credentials/state."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read iLink JSON store: %s", self._path)
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
        if os.name == "posix":
            try:
                self._path.chmod(0o600)
            except OSError:
                pass


class WeixinIlinkAccountStore:
    def __init__(self, directory: str | Path) -> None:
        self._file = JsonFileStore(Path(directory) / "account.json")

    def load(self) -> WeixinIlinkAccount | None:
        data = self._file.load()
        if not data or not data.get("token"):
            return None
        return WeixinIlinkAccount(
            token=str(data["token"]),
            account_id=str(data.get("account_id", "")),
            base_url=str(data.get("base_url") or DEFAULT_BASE_URL),
            user_id=str(data.get("user_id", "")),
            bot_type=str(data.get("bot_type", "bot")),
        )

    def save(self, account: WeixinIlinkAccount) -> Path:
        self._file.save(account.to_dict())
        return self._file._path


class WeixinIlinkContextStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self._store = JsonFileStore(path) if path is not None else None
        self._tokens: dict[str, str] = {}
        loaded = self._store.load() if self._store is not None else None
        if loaded:
            self._tokens = {str(k): str(v) for k, v in loaded.items()}
        self._lock = asyncio.Lock()

    async def get(self, peer_user_id: str) -> str:
        async with self._lock:
            return self._tokens.get(peer_user_id, "")

    async def set(self, peer_user_id: str, token: str) -> None:
        async with self._lock:
            if token:
                self._tokens[peer_user_id] = token
            else:
                self._tokens.pop(peer_user_id, None)
            self._persist()

    async def clear(self, peer_user_id: str) -> None:
        await self.set(peer_user_id, "")

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(self._tokens)


class _InMemoryDedupStore:
    """TTL-scoped duplicate detector for iLink long-poll redelivery."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            expired = [k for k, expires_at in self._entries.items() if expires_at <= now]
            for k in expired:
                self._entries.pop(k, None)
            if key in self._entries:
                return False
            self._entries[key] = now + self._ttl_seconds
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)


class WeixinIlinkGateway:
    """Long-poll iLink messages and route them to SEMA chat or tasks."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        client: WeixinIlinkClient,
        account: WeixinIlinkAccount,
        default_workspace_id: str = "",
        dm_policy: str = "closed",
        allowed_users: tuple[str, ...] = (),
        dedup_ttl_seconds: float = 300.0,
        router: WeixinIlinkRouter | None = None,
        state_store: WeixinIlinkStateStore | None = None,
        dedup_store: _InMemoryDedupStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._gateway = RuntimeGateway(runtime, transport="weixin_ilink")
        self._client = client
        self._account = account
        self._default_workspace_id = default_workspace_id
        self._dm_policy = dm_policy
        self._allowed_users = frozenset(allowed_users)
        self._warn_about_admission()
        self._router = router or WeixinIlinkRouter()
        self._state_store = state_store or WeixinIlinkStateStore()
        self._dedup = dedup_store or _InMemoryDedupStore(dedup_ttl_seconds)
        self._sync_buf = ""
        self._sync_buf_loaded = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _warn_about_admission(self) -> None:
        """Say out loud whom this gateway admits (audit R10).

        The default used to be ``open``, so a bot whose operator had not filled
        in ``allowed_users`` accepted every sender. Hermes' rule is the opposite
        — "if no allowlists are configured, all users are denied" — and a default
        should not be the permissive one. Both directions log, because a gateway
        that is silently shut looks exactly like a broken one.
        """
        if self._dm_policy == "open":
            logger.warning(
                "weixin_ilink dm_policy=open accepts every sender; set "
                'allowed_users and dm_policy="closed" to restrict who can drive '
                "this agent"
            )
        elif not self._allowed_users:
            logger.warning(
                "weixin_ilink dm_policy=%r with an empty allowed_users ignores "
                'every sender; set allowed_users, or dm_policy="open" to accept '
                "everyone",
                self._dm_policy,
            )

    async def poll_once(self) -> dict[str, Any]:
        if not self._sync_buf_loaded:
            self._sync_buf = await self._state_store.get_sync_buf()
            self._sync_buf_loaded = True
        update = await self._client.get_updates(self._sync_buf)
        next_sync_buf = (
            _first_str(update, "get_updates_buf")
            or _first_str(update, "next_sync_buf")
            or self._sync_buf
        )
        if next_sync_buf != self._sync_buf:
            self._sync_buf = next_sync_buf
            await self._state_store.set_sync_buf(next_sync_buf)
        results = []
        for message in self.parse_updates(update):
            result = await self.handle_inbound(message)
            results.append(result)
        return {"update": update, "results": results}

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError:
                logger.exception("iLink long-poll HTTP error; retrying")
                await asyncio.sleep(1.0)
            except Exception:
                logger.exception("iLink polling error; retrying")
                await asyncio.sleep(2.0)

    async def handle_inbound(
        self,
        message: WeixinIlinkInbound,
        *,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        peer = message.from_user_id
        # Only the literal "open" admits everyone. Anything else -- including a
        # typo in the configured value -- falls back to the allowlist, so a
        # mistyped policy cannot silently widen access (audit R10).
        if self._dm_policy != "open" and peer not in self._allowed_users:
            return {"ok": True, "ignored": "not_allowed"}

        key = message.message_id or self._message_key(message)
        if not await self._dedup.acquire(key):
            return {"ok": True, "ignored": "duplicate"}

        try:
            context_token = message.context_token or await self._state_store.get_context_token(
                peer
            )
            route = self._router.classify(message.text)
            if route.kind == "conversation":
                result = await self._handle_conversation(
                    message,
                    route.instruction,
                    context_token,
                )
            else:
                result = await self._handle_task(
                    message,
                    route.instruction,
                    context_token,
                    workspace_id=workspace_id,
                )
            if message.context_token:
                await self._state_store.set_context_token(peer, message.context_token)
            return result
        except Exception:
            await self._dedup.release(key)
            logger.exception("Failed to process iLink message")
            raise

    async def _handle_conversation(
        self,
        message: WeixinIlinkInbound,
        instruction: str,
        context_token: str,
    ) -> dict[str, Any]:
        peer = message.from_user_id
        session_id = await self._state_store.get_session_id(peer)
        metadata = {"transport": "weixin_ilink"}
        if self._default_workspace_id:
            metadata["workspace_id"] = self._default_workspace_id
        response = await self._gateway.handle_message(
            Message(
                content=instruction,
                channel="weixin_ilink",
                user_id=peer,
                session_id=session_id or None,
                metadata=metadata,
            )
        )
        new_session_id = response.metadata.get("session_id") or session_id
        if new_session_id:
            await self._state_store.set_session_id(peer, str(new_session_id))
        reply = response.content or f"Chat status: {response.status}"
        send_result = await self._send_reply(peer, reply, context_token)
        return {
            "ok": True,
            "task_id": "",
            "session_id": new_session_id,
            "send_result": send_result,
        }

    async def _handle_task(
        self,
        message: WeixinIlinkInbound,
        instruction: str,
        context_token: str,
        *,
        workspace_id: str,
    ) -> dict[str, Any]:
        peer = message.from_user_id
        if not instruction:
            reply = "请补充任务指令，例如：/task 修复 README 中的链接"
            send_result = await self._send_reply(peer, reply, context_token)
            return {"ok": True, "task_id": "", "send_result": send_result}

        target_workspace = workspace_id or self._default_workspace_id
        if not target_workspace:
            reply = "微信任务模式未配置 workspace，无法创建任务"
            send_result = await self._send_reply(peer, reply, context_token)
            return {"ok": True, "task_id": "", "send_result": send_result}

        task = await self._runtime.create_task(
            target_workspace,
            instruction,
            actor=Principal(user_id=peer),
            source="weixin_ilink",
            message_id=message.message_id,
            delegation_scope=DelegationScope(
                allowed_actions=frozenset({"file.read"}),
            ),
        )
        await self._state_store.set_last_task_id(peer, task.id)
        reply = f"已创建任务：{task.id}\n正在执行，请稍候..."
        send_result = await self._send_reply(peer, reply, context_token)
        self._spawn_task_lifecycle(task, peer, context_token)
        return {
            "ok": True,
            "task_id": task.id,
            "send_result": send_result,
        }

    def _spawn_task_lifecycle(
        self,
        task: Task,
        peer: str,
        context_token: str,
    ) -> None:
        background = asyncio.create_task(
            self._run_task_lifecycle(task, peer, context_token),
            name=f"weixin-task-{task.id}",
        )
        self._background_tasks.add(background)
        background.add_done_callback(self._background_tasks.discard)

    async def _run_task_lifecycle(
        self,
        task: Task,
        peer: str,
        context_token: str,
    ) -> None:
        try:
            result = await self._runtime.execute(task)
        except Exception as exc:
            await self._send_reply(peer, f"任务执行失败：{exc}", context_token)
            return

        if result.status is TaskStatus.WAITING_APPROVAL:
            await self._send_reply(
                peer,
                f"任务 {task.id} 等待人工审批",
                context_token,
            )
            result = await self._wait_for_decision(task, peer, context_token)
            if result is None:
                return

        reply = await self._task_reply(task.id, result)
        await self._send_reply(peer, reply, context_token)

    async def _wait_for_decision(
        self,
        task: Task,
        peer: str,
        context_token: str,
    ) -> TaskResult | None:
        while True:
            await asyncio.sleep(1.0)
            current = await self._runtime.get_task(task.id)
            if current is None:
                return None
            proposals = await self._runtime.list_change_proposals(task.id)
            statuses = {proposal.status.value for proposal in proposals}

            if "rejected" in statuses:
                await self._send_reply(peer, "任务已被拒绝", context_token)
                return None

            if current.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return TaskResult(task_id=current.id, status=current.status)

            if current.status is TaskStatus.WAITING_APPROVAL and (
                "approved" in statuses or "applied" in statuses
            ):
                return await self._runtime.resume_task(current)

    async def _task_reply(self, task_id: str, result: TaskResult) -> str:
        if result.status is TaskStatus.COMPLETED:
            if result.content:
                return result.content
            content = await self._task_agent_content(task_id)
            return content or "任务已完成"
        if result.status is TaskStatus.FAILED:
            return f"任务失败：{result.error or 'unknown error'}"
        return f"任务状态：{result.status.value}"

    async def _task_agent_content(self, task_id: str) -> str:
        metadata = self._runtime.storage.metadata
        if metadata is None:
            return ""
        nodes = await metadata.list_execution_nodes(task_id)
        for node in reversed(nodes):
            if node.type.value != "agent":
                continue
            output = node.metadata.get("output") if isinstance(node.metadata, dict) else None
            if isinstance(output, dict) and output.get("content"):
                return str(output["content"])
        return ""

    def parse_updates(
        self,
        payload: dict[str, Any],
    ) -> list[WeixinIlinkInbound]:
        messages = payload.get("msgs") or payload.get("messages") or []
        if isinstance(messages, dict):
            messages = [messages]
        parsed: list[WeixinIlinkInbound] = []
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            message = self._parse_inbound(raw)
            if message is not None:
                parsed.append(message)
        return parsed

    def _parse_inbound(self, raw: dict[str, Any]) -> WeixinIlinkInbound | None:
        message_type = _first_int(raw, "msg_type", "message_type")
        if message_type != _MESSAGE_TYPE_USER:
            return None
        from_user_id = _first_str(raw, "from_user_id", "sender_id")
        to_user_id = _first_str(raw, "to_user_id", "receiver_id")
        room_id = _first_str(raw, "room_id", "chat_room_id", "group_id")
        is_group = bool(room_id) or (
            bool(to_user_id)
            and bool(self._account.account_id)
            and to_user_id != self._account.account_id
            and message_type == _MESSAGE_TYPE_USER
        )
        if is_group:
            return None
        text = _extract_text(raw.get("item_list"))
        if not text or not from_user_id:
            return None
        message_id = _first_str(raw, "client_id", "message_id", "msg_id")
        return WeixinIlinkInbound(
            from_user_id=from_user_id,
            text=text,
            message_id=message_id,
            context_token=_first_str(raw, "context_token"),
        )

    async def _send_reply(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
    ) -> dict[str, Any]:
        result = await self._client.send_text(
            to_user_id,
            text,
            context_token=context_token,
        )
        if _is_stale_context(result) and context_token:
            await self._state_store.clear_context_token(to_user_id)
            result = await self._client.send_text(to_user_id, text, context_token="")
        return result

    @staticmethod
    def _message_key(message: WeixinIlinkInbound) -> str:
        raw = "\0".join(
            (
                message.from_user_id,
                message.text,
                message.context_token,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_text(item_list: Any) -> str:
    if not isinstance(item_list, list):
        return ""
    for item in item_list:
        if not isinstance(item, dict):
            continue
        if _first_int(item, "type") == _ITEM_TYPE_TEXT:
            text_item = item.get("text_item")
            if isinstance(text_item, dict):
                text = _first_str(text_item, "text", "content")
            else:
                text = _first_str(item, "text", "content")
            if text:
                return text
    return ""


def _is_stale_context(result: dict[str, Any]) -> bool:
    return _first_int(result, "errcode", "ret") in {-14, -3, -2}


__all__ = [
    "DEFAULT_BASE_URL",
    "WeixinIlinkAccount",
    "WeixinIlinkAccountStore",
    "WeixinIlinkClient",
    "WeixinIlinkContextStore",
    "WeixinIlinkGateway",
    "WeixinIlinkInbound",
    "WeixinIlinkRouter",
    "WeixinIlinkStateStore",
]

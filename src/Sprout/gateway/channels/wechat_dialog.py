"""WeChat Dialog Open Platform adapter.

This module implements the third-party customer-service callback flow:
WeChat forwards an encrypted user message to our callback, we decrypt it,
run the message through SEMA, and send the reply back through the
``openapi/sendmsg`` endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import sqlite3
import struct
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.runtime.runtime import Runtime
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.task.models import DelegationScope

logger = logging.getLogger("sprout.gateway.wechat_dialog")


def _decode_aes_key(encoding_aes_key: str) -> bytes:
    """Decode the 43-character WeChat ``EncodingAESKey`` into 32 bytes."""
    if not encoding_aes_key:
        raise ValueError("EncodingAESKey is empty")
    try:
        key = base64.b64decode(encoding_aes_key + "=")
    except Exception as exc:  # noqa: BLE001 - normalize malformed key errors
        raise ValueError("EncodingAESKey is not valid base64") from exc
    if len(key) != 32:
        raise ValueError("EncodingAESKey must decode to 32 bytes")
    return key


def _pkcs7_pad(data: bytes, block_size: int = 32) -> bytes:
    padding = block_size - (len(data) % block_size)
    return data + bytes([padding]) * padding


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty encrypted payload")
    padding = data[-1]
    if padding < 1 or padding > 32 or padding > len(data):
        raise ValueError("invalid PKCS#7 padding")
    if data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]


@dataclass(slots=True)
class WeChatDialogEvent:
    userid: str
    appid: str
    content: str
    from_type: int
    channel: int
    kfstate: int
    event: str
    assessment: int
    createtime: str = ""


class _InMemoryDedupStore:
    """TTL-scoped duplicate detector for WeChat callback retries."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, ttl_seconds: float | None = None) -> bool:
        ttl_seconds = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        async with self._lock:
            now = time.monotonic()
            expired = [k for k, expires_at in self._entries.items() if expires_at <= now]
            for k in expired:
                self._entries.pop(k, None)
            if key in self._entries:
                return False
            self._entries[key] = now + ttl_seconds
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)


class SqliteDedupStore:
    """Durable duplicate detector for multi-process WeChat deployments."""

    def __init__(self, db: SqliteDatabase) -> None:
        self._db = db
        db.execute_sync(
            """
            CREATE TABLE IF NOT EXISTS wechat_dialog_dedup (
                key TEXT PRIMARY KEY,
                expires_at REAL NOT NULL
            )
            """
        )

    async def acquire(self, key: str, ttl_seconds: float | None = None) -> bool:
        ttl_seconds = ttl_seconds if ttl_seconds is not None else 300.0
        now = time.time()
        await self._db.execute(
            "DELETE FROM wechat_dialog_dedup WHERE expires_at <= ?",
            (now,),
        )
        try:
            await self._db.execute(
                "INSERT INTO wechat_dialog_dedup(key, expires_at) VALUES (?, ?)",
                (key, now + ttl_seconds),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    async def release(self, key: str) -> None:
        await self._db.execute(
            "DELETE FROM wechat_dialog_dedup WHERE key = ?",
            (key,),
        )


class WeChatDialogClient:
    """HTTP and crypto client for the WeChat Dialog Open Platform."""

    def __init__(
        self,
        *,
        token: str,
        encoding_aes_key: str,
        appid: str = "",
        base_url: str = "https://chatbot.weixin.qq.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._encoding_aes_key = encoding_aes_key
        self._appid = appid
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def encrypt_message(self, plaintext: str, *, appid: str = "") -> str:
        """Encrypt a payload using WeChat's AES-CBC message format."""
        appid = appid or self._appid
        key = _decode_aes_key(self._encoding_aes_key)
        plaintext_bytes = plaintext.encode("utf-8")
        raw = (
            secrets.token_bytes(16)
            + struct.pack("!I", len(plaintext_bytes))
            + plaintext_bytes
            + appid.encode("utf-8")
        )
        padded = _pkcs7_pad(raw)
        encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(encrypted).decode("ascii")

    def decrypt_message(self, encrypted: str) -> str:
        """Decrypt a WeChat callback payload and return its XML text."""
        key = _decode_aes_key(self._encoding_aes_key)
        try:
            ciphertext = base64.b64decode(encrypted)
        except Exception as exc:  # noqa: BLE001 - normalize malformed payload errors
            raise ValueError("encrypted payload is not valid base64") from exc
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        plain_padded = decryptor.update(ciphertext) + decryptor.finalize()
        plain = _pkcs7_unpad(plain_padded)
        if len(plain) < 20:
            raise ValueError("decrypted payload is too short")
        msg_len = struct.unpack("!I", plain[16:20])[0]
        message = plain[20 : 20 + msg_len]
        if len(message) != msg_len:
            raise ValueError("decrypted message length mismatch")
        return message.decode("utf-8")

    async def send_message(
        self,
        openid: str,
        msg: str,
        channel: int,
        *,
        appid: str = "",
        kefuname: str = "",
        kefuavatar: str = "",
        ans_node_name: str = "",
    ) -> dict[str, Any]:
        """Send a customer-service message through ``openapi/sendmsg``."""
        payload = self._build_send_payload(
            openid=openid,
            msg=msg,
            channel=channel,
            appid=appid or self._appid,
            kefuname=kefuname,
            kefuavatar=kefuavatar,
            ans_node_name=ans_node_name,
        )
        encrypted = self.encrypt_message(payload, appid=appid or self._appid)
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            transport=self._transport,
        ) as client:
            response = await client.post(
                f"/openapi/sendmsg/{self._token}",
                json={"encrypt": encrypted},
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _build_send_payload(
        *,
        openid: str,
        msg: str,
        channel: int,
        appid: str,
        kefuname: str,
        kefuavatar: str,
        ans_node_name: str,
    ) -> str:
        root = ET.Element("xml")
        if appid:
            ET.SubElement(root, "appid").text = appid
        ET.SubElement(root, "openid").text = openid
        ET.SubElement(root, "msg").text = msg
        ET.SubElement(root, "channel").text = str(channel)
        if kefuname:
            ET.SubElement(root, "kefuname").text = kefuname
        if kefuavatar:
            ET.SubElement(root, "kefuavatar").text = kefuavatar
        if ans_node_name:
            ET.SubElement(root, "ans_node_name").text = ans_node_name
        return ET.tostring(root, encoding="unicode")


class WeChatDialogGateway:
    """Maps WeChat Dialog callbacks to SEMA Tasks and sends replies back."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        client: WeChatDialogClient | None = None,
        default_workspace_id: str = "",
        default_channel: int = 0,
        default_appid: str = "",
        dedup_window_seconds: float = 300.0,
        workspace_by_channel: dict[str, str] | None = None,
        workspace_by_user: dict[str, str] | None = None,
        dedup_store: _InMemoryDedupStore | SqliteDedupStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._gateway = RuntimeGateway(runtime, transport="wechat_dialog")
        self._client = client
        self._default_workspace_id = default_workspace_id
        self._default_channel = default_channel
        self._default_appid = default_appid
        self._workspace_by_channel = dict(workspace_by_channel or {})
        self._workspace_by_user = dict(workspace_by_user or {})
        self._dedup_window_seconds = dedup_window_seconds
        self._dedup = dedup_store or _InMemoryDedupStore(dedup_window_seconds)

    async def handle_callback(self, body: dict[str, Any]) -> dict[str, Any]:
        event, reason = await self._claim_event(body)
        if event is None:
            return {"ok": True, "ignored": reason}
        return await self.process_event(event)

    async def ack_callback(
        self,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], WeChatDialogEvent | None]:
        """Claim an event and return immediately without executing the Task."""
        event, reason = await self._claim_event(body)
        if event is None:
            return {"ok": True, "ignored": reason}, None
        return {"ok": True, "queued": True}, event

    async def process_event(self, event: WeChatDialogEvent) -> dict[str, Any]:
        if self._client is None:
            raise ValueError("WeChatDialogGateway requires a client for callbacks")
        key = self._event_key(event)
        try:
            response = await self._gateway.execute(
                GatewayRequest(
                    transport="wechat_dialog",
                    instruction=event.content,
                    caller=Principal(user_id=event.userid),
                    workspace_id=self._resolve_workspace(event),
                    delegation_scope=DelegationScope(
                        allowed_actions=frozenset({"file.read"}),
                    ),
                )
            )
            reply = response.content or f"Task status: {response.status}"
            channel = event.channel if event.channel >= 0 else self._default_channel
            send_result = await self._client.send_message(
                openid=event.userid,
                msg=reply,
                channel=channel,
                appid=event.appid or self._default_appid,
            )
            return {
                "ok": True,
                "task_id": response.task_id,
                "send_result": send_result,
            }
        except Exception:
            await self._dedup.release(key)
            logger.exception("Failed to process WeChat Dialog callback")
            raise

    async def _claim_event(
        self,
        body: dict[str, Any],
    ) -> tuple[WeChatDialogEvent | None, str]:
        if self._client is None:
            raise ValueError("WeChatDialogGateway requires a client for callbacks")
        encrypted = body.get("encrypted") if isinstance(body, dict) else None
        if not isinstance(encrypted, str) or not encrypted:
            raise ValueError("missing 'encrypted' field")

        event = self.parse_event(self._client.decrypt_message(encrypted))
        if event.from_type != 0:
            return None, "non_user_message"
        if not event.content:
            return None, "empty_content"
        if not await self._dedup.acquire(
            self._event_key(event),
            self._dedup_window_seconds,
        ):
            return None, "duplicate"
        return event, ""

    async def handle_query(
        self,
        query: str,
        userid: str,
        *,
        workspace_id: str = "",
    ) -> GatewayResponse:
        """Run a direct query through SEMA without using a WeChat callback."""
        return await self._gateway.execute(
            GatewayRequest(
                transport="wechat_dialog",
                instruction=query,
                caller=Principal(user_id=userid),
                workspace_id=workspace_id or self._default_workspace_id,
                delegation_scope=DelegationScope(
                    allowed_actions=frozenset({"file.read"}),
                ),
            )
        )

    def _resolve_workspace(self, event: WeChatDialogEvent) -> str:
        workspace_id = self._workspace_by_channel.get(str(event.channel))
        if workspace_id:
            return workspace_id
        workspace_id = self._workspace_by_user.get(event.userid)
        if workspace_id:
            return workspace_id
        return self._default_workspace_id

    @staticmethod
    def parse_event(xml_text: str) -> WeChatDialogEvent:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise ValueError("callback payload is not valid XML") from exc

        def text(path: str) -> str:
            node = root.find(path)
            return (node.text or "").strip() if node is not None else ""

        content_node = root.find("content")
        content = WeChatDialogGateway._content_text(content_node)
        return WeChatDialogEvent(
            userid=text("userid"),
            appid=text("appid"),
            content=content,
            from_type=_as_int(text("from"), default=-1),
            channel=_as_int(text("channel"), default=-1),
            kfstate=_as_int(text("kfstate"), default=0),
            event=text("event"),
            assessment=_as_int(text("assessment"), default=0),
            createtime=text("createtime"),
        )

    @staticmethod
    def _content_text(node: ET.Element | None) -> str:
        if node is None:
            return ""
        msg = node.find("msg")
        if msg is not None and msg.text:
            return msg.text.strip()
        return "".join(node.itertext()).strip()

    @staticmethod
    def _event_key(event: WeChatDialogEvent) -> str:
        raw = "\0".join(
            (
                event.userid,
                str(event.channel),
                event.createtime,
                event.content,
                str(event.from_type),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

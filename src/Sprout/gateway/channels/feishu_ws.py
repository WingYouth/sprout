"""Feishu WebSocket long-connection gateway.

The webhook adapter in :mod:`Sprout.gateway.channels.feishu` requires a public
callback URL.  Feishu also exposes a long-connection mode that needs no public
endpoint, which is what Hermes-style local gateways use.  This module wraps the
official ``lark-oapi`` SDK for that path.

The SDK drives its own event loop on the calling thread and its ``start()``
call blocks.  SEMA's Runtime is async, so this adapter owns a dedicated worker
loop on a background thread and bridges the two with
``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import threading
from typing import Any

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import DelegationScope, TaskResult, TaskStatus

logger = logging.getLogger(__name__)

# Feishu renders an @-mention as an opaque ``@_user_N`` token inside the text.
_AT_MENTION_RE = re.compile(r"@_user_\d+")


class FeishuWebSocketGateway:
    """Receive Feishu events over a long connection and map text into Tasks."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        encrypt_key: str = "",
        default_workspace_id: str = "",
        domain: str = "feishu",
        log_level: str = "info",
        reply_client: Any | None = None,
    ) -> None:
        self._runtime = runtime
        self._gateway = RuntimeGateway(runtime, transport="feishu")
        self._app_id = app_id
        self._app_secret = app_secret
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._default_workspace_id = default_workspace_id
        self._domain = domain
        self._log_level = log_level
        self._reply_client = reply_client
        if not verification_token:
            logger.info(
                "Feishu verification token is empty; WebSocket long-connection "
                "mode authenticates events through the SDK connection, so no "
                "verification token is required."
            )
        elif not encrypt_key:
            logger.info(
                "Feishu verification token is set; WebSocket mode does not "
                "consume it, but it is retained for webhook deployments."
            )

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="feishu-ws-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The worker loop all async Runtime work is scheduled onto."""
        return self._loop

    def submit(self, coro: Any) -> concurrent.futures.Future:
        """Schedule ``coro`` on the worker loop from any thread."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def build_event_handler(self) -> Any:
        """Build the SDK dispatcher and register the receive-message event."""
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder

        builder = EventDispatcherHandlerBuilder(
            # Was hard-coded to "", which told the SDK there was nothing to
            # decrypt or verify even when the operator had configured a key.
            encrypt_key=self._encrypt_key,
            verification_token=self._verification_token,
        )
        builder.register_p2_im_message_receive_v1(self._on_receive)
        return builder.build()

    def start(self) -> None:
        """Connect and block the calling thread on the SDK loop."""
        from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN
        from lark_oapi.ws import Client as WsClient

        domain = FEISHU_DOMAIN if self._domain == "feishu" else LARK_DOMAIN
        self._ws = WsClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=self.build_event_handler(),
            domain=domain,
            log_level=_lark_log_level(self._log_level),
            auto_reconnect=True,
        )
        self._ws.start()

    def stop(self) -> None:
        """Shut down the worker loop and release the background thread."""
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)

    def _on_receive(self, event: Any) -> None:
        logger.info("Feishu message event received")
        future = self.submit(self._handle_receive(event))
        future.add_done_callback(self._log_failure)

    @staticmethod
    def _log_failure(future: concurrent.futures.Future) -> None:
        exc = future.exception()
        if exc is not None:
            logger.exception("Feishu event failed", exc_info=exc)

    async def _handle_receive(self, event: Any) -> None:
        try:
            data = event.event
            message = data.message
            sender = data.sender
            sender_type = getattr(sender, "sender_type", None)
            if sender_type == "app":
                logger.info("ignoring bot message")
                return

            text = _AT_MENTION_RE.sub("", self._extract_text(message)).strip()
            chat_type = getattr(message, "chat_type", "") or "p2p"
            logger.info(
                "Feishu inbound sender_type=%s chat_type=%s text=%r",
                sender_type,
                chat_type,
                text,
            )
            if not text:
                return

            if chat_type == "group":
                receive_id = getattr(message, "chat_id", "") or ""
                receive_id_type = "chat_id"
            else:
                receive_id = self._sender_open_id(sender)
                receive_id_type = "open_id"

            response = await self._gateway.execute(
                GatewayRequest(
                    transport="feishu",
                    instruction=text,
                    caller=Principal(
                        user_id=self._sender_open_id(sender) or "feishu-user",
                        authenticated=False,
                        source="feishu",
                    ),
                    workspace_id=self._default_workspace_id,
                    delegation_scope=DelegationScope(
                        allowed_actions=frozenset({"file.read"}),
                    ),
                )
            )

            if response.status == TaskStatus.WAITING_APPROVAL.value:
                await self._send_reply(
                    receive_id,
                    receive_id_type,
                    f"任务 {response.task_id} 等待人工审批",
                )
                result = await self._wait_for_decision(
                    response.task_id,
                    receive_id,
                    receive_id_type,
                )
                if result is None:
                    return
            else:
                result = TaskResult(
                    task_id=response.task_id,
                    status=TaskStatus(response.status),
                    content=response.content,
                )

            reply = await self._task_reply(response.task_id, result)

            logger.info(
                "Feishu reply receive_id=%s receive_id_type=%s len=%d",
                receive_id,
                receive_id_type,
                len(reply),
            )
            await self._send_reply(receive_id, receive_id_type, reply)
            logger.info("Feishu reply sent")
        except Exception:
            logger.exception("Feishu message handling failed")

    async def _send_reply(self, receive_id: str, receive_id_type: str, text: str) -> None:
        """Send one text reply to the originating Feishu chat/user."""
        if self._reply_client is not None and receive_id:
            await self._reply_client.send_text(
                receive_id,
                text,
                receive_id_type=receive_id_type,
            )

    async def _wait_for_decision(
        self,
        task_id: str,
        receive_id: str,
        receive_id_type: str,
    ) -> TaskResult | None:
        """Poll a parked task until its change proposal is decided, then resume."""
        while True:
            await asyncio.sleep(1.0)
            current = await self._runtime.get_task(task_id)
            if current is None:
                return None
            proposals = await self._runtime.list_change_proposals(task_id)
            statuses = {proposal.status.value for proposal in proposals}

            if "rejected" in statuses:
                await self._send_reply(receive_id, receive_id_type, "任务已被拒绝")
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
        """Render the final task result for a Feishu reply."""
        if result.status is TaskStatus.COMPLETED:
            if result.content:
                return result.content
            content = await self._task_agent_content(task_id)
            return content or "任务已完成"
        if result.status is TaskStatus.FAILED:
            return f"任务失败：{result.error or 'unknown error'}"
        return f"任务状态：{result.status.value}"

    async def _task_agent_content(self, task_id: str) -> str:
        """Read the last agent node's textual output for a completed task."""
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

    @staticmethod
    def _sender_open_id(sender: Any) -> str:
        sender_id = getattr(sender, "sender_id", None)
        if sender_id is None:
            return ""
        return str(
            getattr(sender_id, "open_id", "")
            or getattr(sender_id, "user_id", "")
            or getattr(sender_id, "union_id", "")
            or ""
        )

    @staticmethod
    def _extract_text(message: Any) -> str:
        message_type = getattr(message, "message_type", "") or "text"
        content = getattr(message, "content", "") or ""
        if message_type == "post":
            return _extract_post_text(content)

        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            return content
        if isinstance(payload, dict):
            return str(payload.get("text") or "")
        return str(content)


def _extract_post_text(content: str) -> str:
    """Flatten Feishu ``post`` rich-text payloads into plain text."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""

    root = payload.get("post", payload)
    if not isinstance(root, dict):
        return ""

    def block_text(block: dict) -> str:
        parts: list[str] = []
        title = block.get("title")
        if isinstance(title, str):
            parts.append(title)
        for row in block.get("content") or []:
            if not isinstance(row, list):
                continue
            for element in row:
                if not isinstance(element, dict):
                    continue
                tag = element.get("tag")
                if tag in {"text", "a"}:
                    parts.append(str(element.get("text") or ""))
                elif tag == "at":
                    parts.append(f"@{element.get('user_name', 'user')}")
        return " ".join(part for part in parts if part)

    if isinstance(root.get("content"), list):
        text = block_text(root)
        if text:
            return text

    for locale in ("zh_cn", "en_us", "ja_jp"):
        localized = root.get(locale)
        if isinstance(localized, dict):
            text = block_text(localized)
            if text:
                return text

    for value in root.values():
        if isinstance(value, dict):
            text = block_text(value)
            if text:
                return text
    return ""


def _lark_log_level(name: str) -> Any:
    """Map a friendly log-level name to the SDK enum."""
    import lark_oapi as lark

    levels = {
        "debug": lark.LogLevel.DEBUG,
        "info": lark.LogLevel.INFO,
        "warning": lark.LogLevel.WARNING,
        "error": lark.LogLevel.ERROR,
        "critical": lark.LogLevel.CRITICAL,
    }
    return levels.get(name.lower(), lark.LogLevel.INFO)

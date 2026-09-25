"""Feishu bot gateway adapter.

This adapter handles the common Feishu event envelope and maps incoming text
messages into SEMA Tasks. Transport credentials are injected by the caller.

Verification — the part that used to be missing
-----------------------------------------------
``verify_event`` only ever ran for the ``url_verification`` handshake, so a
``im.message.receive_v1`` event was executed without being checked at all:
anyone who could POST to the callback URL could drive the agent and pick the
workspace. Two checks now run before *every* event is interpreted:

* the **verification token** (``header.token`` on v2 envelopes, ``token`` on the
  handshake) compared in constant time;
* the **request signature**, when an ``encrypt_key`` is configured —
  ``sha256(timestamp + nonce + encrypt_key + raw_body)`` against
  ``X-Lark-Signature``. Because the signed material includes the timestamp, a
  captured callback stops being replayable once it is older than
  :attr:`FeishuGateway.max_clock_skew_seconds`.

A gateway with no verification token configured refuses every event instead of
accepting all of them — the same fail-closed rule ``weixin_ilink`` applies to
its admission policy.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from Sprout.gateway.identity import Principal
from Sprout.gateway.runtime_gateway import RuntimeGateway
from Sprout.gateway.task_adapter import GatewayRequest, GatewayResponse
from Sprout.runtime.runtime import Runtime
from Sprout.task.models import DelegationScope

SIGNATURE_HEADER = "X-Lark-Signature"
TIMESTAMP_HEADER = "X-Lark-Request-Timestamp"
NONCE_HEADER = "X-Lark-Request-Nonce"

#: How far the signed timestamp may drift from local time before a callback is
#: treated as a replay.
DEFAULT_MAX_CLOCK_SKEW_SECONDS = 300.0


def _header(headers: Any, name: str) -> str:
    """Read one header from a Starlette ``Headers`` or a plain mapping."""
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    for candidate in (name, name.lower(), name.upper()):
        value = getter(candidate)
        if value:
            return str(value)
    return ""


class FeishuGateway:
    def __init__(
        self,
        runtime: Runtime,
        *,
        verification_token: str,
        default_workspace_id: str = "",
        encrypt_key: str | None = None,
        max_clock_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    ) -> None:
        self._runtime = runtime
        self._gateway = RuntimeGateway(runtime, transport="feishu")
        self._verification_token = verification_token
        self._default_workspace_id = default_workspace_id
        self._encrypt_key = encrypt_key or ""
        self.max_clock_skew_seconds = max_clock_skew_seconds

    @property
    def verification_enabled(self) -> bool:
        """False when the operator never supplied a verification token."""
        return bool(self._verification_token)

    @property
    def signature_enabled(self) -> bool:
        """True when an encrypt key makes signature checking possible."""
        return bool(self._encrypt_key)

    # -- verification ------------------------------------------------------
    @staticmethod
    def presented_token(body: dict[str, Any]) -> str:
        """The token the caller claims, from either envelope shape."""
        header = body.get("header")
        if isinstance(header, dict):
            token = header.get("token")
            if isinstance(token, str) and token:
                return token
        token = body.get("token")
        return token if isinstance(token, str) else ""

    def verify_token(self, body: dict[str, Any]) -> bool:
        if not self._verification_token:
            return False
        presented = self.presented_token(body)
        if not presented:
            return False
        return hmac.compare_digest(
            presented.encode("utf-8"), self._verification_token.encode("utf-8")
        )

    def verify_signature(self, headers: Any, raw_body: bytes) -> bool:
        """Check ``X-Lark-Signature``; False when it cannot be checked."""
        if not self._encrypt_key:
            return False
        timestamp = _header(headers, TIMESTAMP_HEADER)
        nonce = _header(headers, NONCE_HEADER)
        signature = _header(headers, SIGNATURE_HEADER)
        if not (timestamp and nonce and signature):
            return False
        try:
            drift = abs(time.time() - float(timestamp))
        except ValueError:
            return False
        if drift > self.max_clock_skew_seconds:
            return False
        digest = hashlib.sha256(
            timestamp.encode("utf-8")
            + nonce.encode("utf-8")
            + self._encrypt_key.encode("utf-8")
            + raw_body
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    def require_authentic(
        self, body: dict[str, Any], *, headers: Any = None, raw_body: bytes = b""
    ) -> None:
        """Raise ``ValueError`` unless the callback is provably from Feishu."""
        if not self.verification_enabled:
            raise ValueError(
                "Feishu callback refused: no verification token is configured "
                "(set the variable named by settings.feishu.verification_token_env)"
            )
        if not self.verify_token(body):
            raise ValueError("Feishu callback failed the verification-token check")
        if self.signature_enabled and not self.verify_signature(headers, raw_body):
            raise ValueError("Feishu callback failed the request-signature check")

    # -- handshake ---------------------------------------------------------
    def verify_event(self, body: dict[str, Any]) -> bool:
        if body.get("type") != "url_verification":
            return False
        return self.verify_token(body)

    def url_verification(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self.verify_event(body):
            return None
        return {"challenge": body.get("challenge")}

    # -- event handling ----------------------------------------------------
    async def handle_event(
        self,
        body: dict[str, Any],
        *,
        headers: Any = None,
        raw_body: bytes = b"",
    ) -> GatewayResponse | dict[str, Any]:
        self.require_authentic(body, headers=headers, raw_body=raw_body)

        event_type = str(body.get("event_type") or body.get("type") or "")
        if event_type == "url_verification":
            verified = self.url_verification(body)
            if verified is None:
                raise ValueError("Feishu URL verification failed")
            return verified

        header = body.get("header") if isinstance(body.get("header"), dict) else {}
        event = body.get("event") if isinstance(body.get("event"), dict) else body
        header_type = header.get("event_type")
        if event_type != "im.message.receive_v1" and header_type != "im.message.receive_v1":
            raise ValueError(f"Unsupported Feishu event type: {event_type}")

        sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        # Loop prevention only: this field is caller-supplied, so it is not a
        # security boundary and nothing is authorised on the strength of it.
        if sender.get("sender_type") == "app":
            return {"ok": True, "ignored": "bot_message"}
        sender_id = self._extract_sender_id(sender)
        text = self._extract_text(message)
        workspace_id = body.get("workspace_id") or self._default_workspace_id

        response = await self._gateway.execute(
            GatewayRequest(
                transport="feishu",
                instruction=text,
                caller=Principal(user_id=sender_id, source="feishu"),
                workspace_id=workspace_id,
                delegation_scope=DelegationScope(
                    allowed_actions=frozenset({"file.read"}),
                ),
            )
        )
        return response

    @staticmethod
    def build_text_reply(response: GatewayResponse) -> dict[str, Any]:
        return {
            "msg_type": "text",
            "content": {
                "text": response.content or f"Task status: {response.status}",
            },
        }

    @staticmethod
    def _extract_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return str(content.get("text") or "")
        return str(message.get("text") or "")

    @staticmethod
    def _extract_sender_id(sender: dict[str, Any]) -> str:
        raw = sender.get("sender_id")
        if isinstance(raw, dict):
            return str(
                raw.get("open_id")
                or raw.get("user_id")
                or raw.get("union_id")
                or "feishu-user"
            )
        return str(
            raw
            or sender.get("open_id")
            or sender.get("user_id")
            or "feishu-user"
        )


__all__ = [
    "DEFAULT_MAX_CLOCK_SKEW_SECONDS",
    "NONCE_HEADER",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "FeishuGateway",
]

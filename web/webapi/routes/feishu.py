"""Feishu event callback route.

The callback is an unauthenticated-by-default HTTP surface, so the gateway has
to prove the caller is Feishu before any event is interpreted (AUTHZ §2.1). A
missing verification token is a configuration error, not a reason to accept
everything: the route is simply not registered, mirroring
:mod:`web.webapi.routes.wechat_dialog`.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.gateway.channels.feishu import FeishuGateway
from Sprout.gateway.channels.feishu_client import FeishuClient

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime

logger = logging.getLogger("sprout.web.feishu")


def create_feishu_routes(runtime: Runtime, settings: Settings | None) -> list[Route]:
    if settings is None or not settings.feishu.enabled:
        return []

    verification_token = os.getenv(settings.feishu.verification_token_env, "")
    if not verification_token:
        logger.warning(
            "Feishu is enabled but %s is empty; the callback route is not "
            "registered because it could not verify its callers",
            settings.feishu.verification_token_env,
        )
        return []
    encrypt_key = os.getenv(settings.feishu.encrypt_key_env) or None
    app_id = os.getenv(settings.feishu.app_id_env, "")
    app_secret = os.getenv(settings.feishu.app_secret_env, "")
    gateway = FeishuGateway(
        runtime,
        verification_token=verification_token,
        default_workspace_id=settings.feishu.default_workspace_id,
        encrypt_key=encrypt_key,
    )
    if encrypt_key:
        logger.info("Feishu callbacks must carry a valid X-Lark-Signature")
    client = (
        FeishuClient(app_id=app_id, app_secret=app_secret)
        if app_id and app_secret
        else None
    )

    async def feishu_event(request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        try:
            gateway.require_authentic(body, headers=request.headers, raw_body=raw)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        try:
            result = await gateway.handle_event(
                body, headers=request.headers, raw_body=raw
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        if isinstance(result, dict):
            return JSONResponse(result)
        if client is not None:
            sender_id = _sender_id(body)
            if sender_id:
                await client.send_text(sender_id, result.content or "done")
            return JSONResponse({"ok": True})
        return JSONResponse(gateway.build_text_reply(result))

    return [
        Route(
            "/api/gateway/feishu/event",
            feishu_event,
            methods=["POST"],
        )
    ]


def _sender_id(body: dict) -> str:
    event = body.get("event") if isinstance(body.get("event"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    raw = sender.get("sender_id")
    if isinstance(raw, dict):
        return str(
            raw.get("open_id")
            or raw.get("user_id")
            or raw.get("union_id")
            or ""
        )
    return str(raw or sender.get("open_id") or "")

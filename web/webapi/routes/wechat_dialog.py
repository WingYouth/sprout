"""WeChat Dialog third-party customer-service callback route."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.gateway.channels.wechat_dialog import (
    SqliteDedupStore,
    WeChatDialogClient,
    WeChatDialogGateway,
)
from Sprout.storage.local.sqlite.driver import SqliteDatabase

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime


def create_wechat_dialog_routes(runtime: Runtime, settings: Settings | None) -> list[Route]:
    if settings is None or not settings.wechat_dialog.enabled:
        return []

    token = os.getenv(settings.wechat_dialog.token_env, "")
    encoding_aes_key = os.getenv(settings.wechat_dialog.encoding_aes_key_env, "")
    appid = os.getenv(settings.wechat_dialog.appid_env, "")
    if not token or not encoding_aes_key:
        return []

    client = WeChatDialogClient(
        token=token,
        encoding_aes_key=encoding_aes_key,
        appid=appid,
    )
    dedup_store = None
    if settings.wechat_dialog.dedup_db_path:
        dedup_store = SqliteDedupStore(
            SqliteDatabase.open(settings.wechat_dialog.dedup_db_path)
        )
    gateway = WeChatDialogGateway(
        runtime,
        client=client,
        default_workspace_id=settings.wechat_dialog.default_workspace_id,
        default_channel=settings.wechat_dialog.default_channel,
        default_appid=appid,
        workspace_by_channel=settings.wechat_dialog.workspace_by_channel,
        workspace_by_user=settings.wechat_dialog.workspace_by_user,
        dedup_store=dedup_store,
    )

    async def wechat_dialog_event(request: Request) -> JSONResponse:
        body = await request.json()
        try:
            result, event = await gateway.ack_callback(body)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if event is not None:
            return JSONResponse(
                result,
                background=BackgroundTask(gateway.process_event, event),
            )
        return JSONResponse(result)

    return [
        Route(
            "/api/gateway/wechat_dialog/event",
            wechat_dialog_event,
            methods=["POST"],
        )
    ]

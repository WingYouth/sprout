"""WebSocket chat endpoint: /ws/chat."""

from __future__ import annotations

from typing import TYPE_CHECKING

from Sprout.message.converter import outbound_to_dict
from Sprout.message.models import Message

from ..auth import caller_user_id

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

    from Sprout.runtime.runtime import Runtime


def create_ws_chat_endpoint(runtime: Runtime):
    async def ws_chat(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    await websocket.send_json({"error": "expected a JSON object"})
                    continue
                content = data.get("message")
                if not isinstance(content, str) or not content.strip():
                    await websocket.send_json({"error": "'message' must be a non-empty string"})
                    continue
                message = Message(
                    content=content,
                    channel="web",
                    # Server-side identity, not the body (AUTHZ §2.1). The auth
                    # middleware closes the socket before the handshake when the
                    # caller cannot present a token, so this endpoint is guarded
                    # even though it is not an HTTP route.
                    user_id=caller_user_id(
                        websocket, str(data.get("user_id") or "web-user")
                    ),
                    session_id=data.get("session_id"),
                )
                if data.get("stream"):
                    try:
                        async for chunk in runtime.handle_stream(message):
                            if chunk.error is not None:
                                await websocket.send_json(
                                    {"type": "error", "message": chunk.error}
                                )
                                break
                            if chunk.content:
                                await websocket.send_json(
                                    {"type": "chunk", "content": chunk.content}
                                )
                            if chunk.outbound is not None:
                                await websocket.send_json(
                                    {
                                        "type": "done",
                                        **outbound_to_dict(chunk.outbound),
                                    }
                                )
                    except Exception as exc:  # noqa: BLE001
                        await websocket.send_json(
                            {"error": f"{type(exc).__name__}: {exc}"}
                        )
                    continue
                try:
                    outbound = await runtime.handle(message)
                except Exception as exc:  # noqa: BLE001 - keep the socket alive
                    await websocket.send_json({"error": f"{type(exc).__name__}: {exc}"})
                    continue
                await websocket.send_json(outbound_to_dict(outbound))
        except Exception:  # noqa: BLE001 - WebSocketDisconnect and friends
            pass

    return ws_chat

"""Chat endpoints: POST /api/chat and GET /api/sessions/{id}/history."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, StreamingResponse

from Sprout.gateway.transport_gateways import WebGateway
from Sprout.message.models import Message

from ..auth import caller_user_id, principal_of

if TYPE_CHECKING:
    from starlette.requests import Request

    from Sprout.runtime.runtime import Runtime


def create_chat_routes(runtime: Runtime) -> list:
    from starlette.routing import Route

    async def chat_endpoint(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        content = data.get("message") if isinstance(data, dict) else None
        if not isinstance(content, str) or not content.strip():
            return JSONResponse({"error": "'message' must be a non-empty string"}, status_code=400)
        message = Message(
            content=content,
            channel="web",
            # Identity comes from the authenticated entry point, never the body
            # (AUTHZ §2.1): naming someone else's user_id used to read and write
            # their sessions and memory.
            user_id=caller_user_id(request, str(data.get("user_id") or "web-user")),
            session_id=data.get("session_id"),
        )
        try:
            response = await WebGateway(runtime).handle_message(message)
        except Exception as exc:  # noqa: BLE001 - surface a clean 500
            return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)
        return JSONResponse(
            {
                "content": response.content,
                "channel": "web",
                "session_id": response.metadata.get("session_id"),
                "correlation_id": response.metadata.get("correlation_id"),
            }
        )

    async def history_endpoint(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        try:
            limit = int(request.query_params.get("limit", "50"))
        except ValueError:
            limit = 50
        owner_error = await _ownership_error(runtime, request, session_id)
        if owner_error is not None:
            return owner_error
        turns = await runtime.history(session_id, limit=limit)
        return JSONResponse(
            {
                "session_id": session_id,
                "turns": [
                    {
                        "role": turn.role,
                        "content": turn.content,
                        "created_at": turn.created_at.isoformat(),
                    }
                    for turn in turns
                ],
            }
        )

    async def resume_endpoint(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        owner_error = await _ownership_error(runtime, request, session_id)
        if owner_error is not None:
            return owner_error
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str) or not content.strip():
            content = "Continue"
        try:
            outbound = await runtime.resume_pending(
                session_id,
                user_id=caller_user_id(
                    request, str(data.get("user_id") or "web-user")
                ),
                content=content,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean error
            return JSONResponse(
                {"error": f"{type(exc).__name__}: {exc}"},
                status_code=500,
            )
        return JSONResponse(
            {
                "content": outbound.content,
                "session_id": outbound.session_id,
                "correlation_id": outbound.correlation_id,
            }
        )

    async def stream_endpoint(request: Request) -> StreamingResponse:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        content = data.get("message") if isinstance(data, dict) else None
        if not isinstance(content, str) or not content.strip():
            return JSONResponse(
                {"error": "'message' must be a non-empty string"},
                status_code=400,
            )

        async def events():
            def sse(payload):
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            try:
                message = Message(
                    content=content,
                    channel="web",
                    user_id=caller_user_id(
                        request, str(data.get("user_id") or "web-user")
                    ),
                    session_id=data.get("session_id"),
                )
                async for chunk in WebGateway(runtime).handle_stream(message):
                    if chunk.error is not None:
                        yield sse({"type": "error", "message": chunk.error})
                        return
                    if chunk.content:
                        yield sse({"type": "chunk", "content": chunk.content})
                    if chunk.outbound is not None:
                        yield sse(
                            {
                                "type": "done",
                                "session_id": chunk.outbound.session_id,
                                "correlation_id": chunk.outbound.correlation_id,
                                "metadata": dict(chunk.outbound.metadata),
                            }
                        )
            except Exception as exc:  # noqa: BLE001 - surface stream errors to the client
                yield sse(
                    {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return [
        Route("/api/chat", chat_endpoint, methods=["POST"]),
        Route("/api/chat/stream", stream_endpoint, methods=["POST"]),
        Route("/api/sessions/{session_id}/history", history_endpoint, methods=["GET"]),
        Route(
            "/api/sessions/{session_id}/resume",
            resume_endpoint,
            methods=["POST"],
        ),
    ]


async def _ownership_error(
    runtime: Runtime, request: Request, session_id: str
) -> JSONResponse | None:
    """Refuse a session the authenticated caller does not own.

    History was readable by anyone who knew a session id. The check only applies
    to authenticated callers, so the unauthenticated loopback default keeps
    working.
    """
    principal = principal_of(request)
    if principal is None or not principal.authenticated:
        return None
    session = await runtime.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    if session.user_id and session.user_id != principal.user_id:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return None

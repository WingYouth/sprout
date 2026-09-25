"""JSON-RPC HTTP endpoint."""

from __future__ import annotations

import hmac
import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.config.settings import Settings
from Sprout.gateway.rpc_gateway import RPCGateway
from Sprout.runtime.runtime import Runtime


def _unauthorized(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "UNAUTHORIZED", "message": message}},
        status_code=status_code,
    )


def create_rpc_routes(runtime: Runtime, settings: Settings | None = None) -> list[Route]:
    gateway = RPCGateway(runtime)
    token_env = "SEMA_RPC_TOKEN"
    token = ""
    auth_enabled = False
    if settings is not None:
        token_env = settings.security.rpc_api_token_env
        auth_enabled = settings.security.rpc_auth_enabled
        token = os.getenv(token_env, "")

    async def rpc_endpoint(request: Request) -> JSONResponse:
        if auth_enabled:
            if not token:
                # ``rpc_auth_enabled`` with an empty token used to fall through to
                # the unauthenticated path, so switching authentication on without
                # also exporting the token silently removed it. Fail closed, and
                # name the variable that is missing.
                return _unauthorized(
                    f"RPC authentication is enabled but {token_env} is empty; "
                    "refusing every request",
                    503,
                )
            presented = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(
                presented.encode("utf-8"), expected.encode("utf-8")
            ):
                return _unauthorized("Invalid or missing RPC token", 401)
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse({"error": "expected JSON object"}, status_code=400)
        return JSONResponse(await gateway.handle(payload))

    return [Route("/api/rpc", rpc_endpoint, methods=["POST"])]

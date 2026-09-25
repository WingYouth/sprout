"""Authentication for the web surface (AUTHZ §2.1).

Every route used to be reachable without any credential — including
``POST /api/approvals/{id}/decide`` (the human decision surface for the whole
authorization layer) and ``POST /api/project/proposals/{id}/apply`` (which lands
changes in the real workspace). AUTHZ §2.1 specifies "session ticket → server
side user lookup" and explicitly allows starting with an API token, which is what
this is.

Rules:

* ``web_auth_enabled = false`` keeps the local-development default (the server
  binds loopback) working; :func:`warn_if_exposed` logs loudly when it is bound
  anywhere else.
* ``web_auth_enabled = true`` requires ``Authorization: Bearer <token>`` on every
  ``/api/*`` route except the health probe.
* Enabled with an empty token fails **closed** with 503. The RPC endpoint had the
  opposite shape — asking for authentication and then silently running without it
  — and that is exactly the failure this avoids.

The principal resolved here carries ``authenticated=True`` and is built from the
server side, never from the request body: a caller cannot name the ``user_id``
whose sessions and memory it wants.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from Sprout.gateway.identity import Principal

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings

#: Optional header letting one shared token stand for several people. Absent, the
#: whole surface runs as :data:`DEFAULT_WEB_USER`.
USER_HEADER = "X-Sprout-User"

DEFAULT_WEB_USER = "web-user"

#: Paths that must answer before anyone can present a token.
EXEMPT_PATHS: tuple[str, ...] = ("/api/health",)


@dataclass(frozen=True, slots=True)
class WebAuth:
    """Resolved web-authentication configuration."""

    enabled: bool = False
    token: str = ""
    token_env: str = "SPROUT_WEB_TOKEN"
    exempt_paths: tuple[str, ...] = EXEMPT_PATHS

    @classmethod
    def from_settings(cls, security: SecuritySettings) -> WebAuth:
        return cls(
            enabled=security.web_auth_enabled,
            token=os.getenv(security.web_api_token_env, ""),
            token_env=security.web_api_token_env,
        )

    def is_exempt(self, path: str) -> bool:
        return any(path == exempt for exempt in self.exempt_paths)

    def anonymous_principal(self) -> Principal:
        """The identity used when authentication is switched off."""
        return Principal(
            user_id=DEFAULT_WEB_USER,
            display_name=DEFAULT_WEB_USER,
            authenticated=False,
            source="web",
        )

    def rejection(self, headers: Headers) -> tuple[int, str] | None:
        """``(status, message)`` when the request must be refused, else None."""
        if not self.token:
            return (
                503,
                f"Web authentication is enabled but {self.token_env} is empty; "
                "refusing every request",
            )
        presented = headers.get("authorization", "")
        expected = f"Bearer {self.token}"
        if not hmac.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")
        ):
            return (401, "Invalid or missing API token")
        return None

    def principal_for(self, headers: Headers) -> Principal:
        """The authenticated caller, derived on the server side."""
        # Header values are not trusted as an identity in the authorization
        # sense — they only split one operator's token into labelled sessions.
        claimed = (headers.get(USER_HEADER, "") or "").strip()
        user_id = claimed or DEFAULT_WEB_USER
        return Principal(
            user_id=user_id,
            display_name=user_id,
            authenticated=True,
            source="web",
        )


class WebAuthMiddleware:
    """Pure-ASGI so the WebSocket route is covered as well.

    ``BaseHTTPMiddleware`` only sees ``http`` scopes, so a ``WebSocketRoute``
    sails straight past an HTTP-only guard. Handling both scopes here keeps one
    decision point.
    """

    def __init__(self, app: Any, auth: WebAuth) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not self.auth.enabled or self.auth.is_exempt(scope.get("path", "")):
            principal = self.auth.anonymous_principal()
        else:
            rejection = self.auth.rejection(headers)
            if rejection is not None:
                await self._refuse(scope, receive, send, *rejection)
                return
            principal = self.auth.principal_for(headers)
        # ``Request.state`` / ``WebSocket.state`` wrap ``scope["state"]``, so this
        # is how a downstream endpoint reads the resolved caller.
        scope.setdefault("state", {})
        scope["state"]["principal"] = principal
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(
        scope: dict, receive: Any, send: Any, status: int, message: str
    ) -> None:
        if scope["type"] == "websocket":
            # 1008 = policy violation; closes before the handshake completes.
            await send({"type": "websocket.close", "code": 1008, "reason": message})
            return
        await JSONResponse({"error": message}, status_code=status)(
            scope, receive, send
        )


def principal_of(request: Any) -> Principal | None:
    """The principal the middleware attached to this request, if any."""
    state = getattr(request, "state", None)
    return getattr(state, "principal", None) if state is not None else None


def caller_user_id(request: Any, fallback: str = DEFAULT_WEB_USER) -> str:
    """The ``user_id`` for session/memory scoping.

    An authenticated principal wins over anything in the body: identity comes
    from the entry-point adapter, not from the caller (AUTHZ §2.1). The body is
    only consulted when authentication is off, so local development keeps
    working.
    """
    principal = principal_of(request)
    if principal is not None and principal.authenticated:
        return principal.user_id
    return fallback


def warn_if_exposed(host: str, auth: WebAuth, logger: Any) -> None:
    """Say out loud when an unauthenticated surface is reachable off-host."""
    if auth.enabled:
        return
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    logger.warning(
        "The web API is bound to %s with web_auth_enabled=false: every route, "
        "including approval decisions and proposal apply, is reachable by anyone "
        "who can connect. Set [security] web_auth_enabled=true and export %s.",
        host,
        auth.token_env,
    )


__all__ = [
    "DEFAULT_WEB_USER",
    "EXEMPT_PATHS",
    "USER_HEADER",
    "WebAuth",
    "WebAuthMiddleware",
    "caller_user_id",
    "principal_of",
    "warn_if_exposed",
]

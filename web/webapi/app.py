"""SEAM_Sprout web application (HTTP + WebSocket), living under ``web/``.

This is the application layer: it imports the installed ``Sprout`` runtime and
exposes it over HTTP. It never implements agent logic itself.

    Browser / HTTP client
            |
    web/webapi (this package)  ->  Runtime.handle()  ->  OutboundMessage

The web layer also owns its own reserved database (``web/webapi/data/webapi.db``),
separate from the runtime's databases.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from Sprout.config.settings import SecuritySettings

from .auth import WebAuth, WebAuthMiddleware
from .database import WebDatabase
from .routes.approvals import create_approval_routes
from .routes.chat import create_chat_routes
from .routes.feishu import create_feishu_routes
from .routes.health import create_health_route
from .routes.logs import create_log_routes
from .routes.project import create_project_routes
from .routes.rpc import create_rpc_routes
from .routes.settings import create_settings_routes
from .routes.storage import create_storage_routes
from .routes.tasks import create_task_routes
from .routes.temporal import create_temporal_routes
from .routes.tokens import create_token_routes
from .routes.wechat_dialog import create_wechat_dialog_routes
from .websocket.chat import create_ws_chat_endpoint

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request

    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime


class RequestAuditMiddleware(BaseHTTPMiddleware):
    """Records every HTTP request into the reserved web database (best-effort)."""

    def __init__(self, app: Any, database: WebDatabase) -> None:
        super().__init__(app)
        self._database = database

    async def dispatch(self, request: Request, call_next: Any):
        started = time.perf_counter()
        status_code: int | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            try:
                await self._database.record_request(
                    route=request.url.path,
                    method=request.method,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                )
            except Exception:  # noqa: BLE001 - auditing must never break responses
                pass


def create_app(
    runtime: Runtime,
    *,
    settings: Settings | None = None,
    database: WebDatabase | None = None,
    static_dir: str | Path | None = None,
    on_startup: Callable[[Runtime], Awaitable[None]] | None = None,
    on_shutdown: Callable[[Runtime], Awaitable[None]] | None = None,
) -> Starlette:
    """Assemble the Starlette application around one runtime."""
    database = database or WebDatabase()

    if static_dir is None:
        candidate = Path.cwd() / "web" / "frontend"
        static_dir = resolve_static_dir(candidate)
    else:
        static_dir = resolve_static_dir(Path(static_dir))

    @asynccontextmanager
    async def lifespan(app: Starlette):
        database.initialize()
        if on_startup is not None:
            await on_startup(runtime)
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()
            if on_shutdown is not None:
                await on_shutdown(runtime)
            database.close()

    routes: list[Any] = [
        Route("/api/health", create_health_route(runtime), methods=["GET"]),
        *create_chat_routes(runtime),
        *create_feishu_routes(runtime, settings),
        *create_wechat_dialog_routes(runtime, settings),
        *create_task_routes(database),
        *create_temporal_routes(),
        *create_token_routes(database),
        *create_log_routes(database),
        *create_settings_routes(settings, database),
        *create_storage_routes(runtime, settings),
        # The runtime project layer: workspaces, tasks, change proposals, and
        # the human approval decisions over them (spec 8.3, 11.5).
        *create_project_routes(runtime),
        # The human decision surface for approvals (AUTHZ §5.2): MCP may only
        # request, so approving lives here and in the CLI.
        *create_approval_routes(runtime),
        *create_rpc_routes(runtime, settings),
        WebSocketRoute("/ws/chat", create_ws_chat_endpoint(runtime)),
    ]
    if static_dir is not None and (Path(static_dir) / "index.html").exists():
        routes.append(
            Mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
        )

    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": "not found"}, status_code=404)

    async def runtime_error(request: Request, exc: Exception) -> JSONResponse:
        """Runtime misconfiguration (e.g. no metadata store) as a clean 500."""
        return JSONResponse({"error": str(exc)}, status_code=500)

    auth = WebAuth.from_settings(
        settings.security if settings is not None else SecuritySettings()
    )

    return Starlette(
        routes=routes,
        middleware=[
            # Outermost first: the audit middleware stays outside authentication
            # so rejected requests are recorded too.
            Middleware(RequestAuditMiddleware, database=database),
            Middleware(WebAuthMiddleware, auth=auth),
        ],
        lifespan=lifespan,
        exception_handlers={404: not_found, RuntimeError: runtime_error},
    )


def resolve_static_dir(candidate: Path) -> Path | None:
    """Prefer the Vite production build, then a direct index.html."""
    if candidate.is_dir():
        built = candidate / "dist"
        if (built / "index.html").exists():
            return built
        if (candidate / "index.html").exists():
            return candidate
    return None

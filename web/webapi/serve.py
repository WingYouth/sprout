"""Serving entry for the web application.

Lives here instead of ``Sprout.cli`` so ``python -m web.webapi`` and the CLI
share one serving path without the web package importing the CLI: the
dependency stays one-way (``Sprout.cli.commands.serve`` -> this module).
Transport wiring (MCP clients, the growth layer) starts inside the serving
event loop through the app lifespan hooks.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette

from .app import create_app, resolve_static_dir
from .auth import WebAuth, warn_if_exposed

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime

logger = logging.getLogger("sprout.web.serve")


def build_serving_app(
    *,
    host: str | None = None,
    port: int | None = None,
    config: str | None = None,
    settings: Settings | None = None,
    runtime: Runtime | None = None,
) -> tuple[Starlette, dict[str, Any]]:
    """Assemble the serving app; returns it with the effective bind info."""
    from Sprout.config.loader import load_settings
    from Sprout.runtime.factory import create_runtime

    settings = settings or load_settings(config)
    runtime = runtime or create_runtime(settings)
    bind_host = host or settings.web.host
    bind_port = port or settings.web.port

    mcp_holder: dict = {}

    async def on_startup(rt: Runtime) -> None:
        if settings.mcp.clients:
            from Sprout.mcp.client import attach_mcp_clients

            mcp_holder["manager"] = await attach_mcp_clients(rt, settings)
        if settings.evolution.enabled:
            from Sprout.evolution import attach_evolution

            attach_evolution(rt, settings)

    async def on_shutdown(rt: Runtime) -> None:
        manager = mcp_holder.pop("manager", None)
        if manager is not None:
            await manager.stop()

    app = create_app(
        runtime,
        settings=settings,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    static_dir = resolve_static_dir(Path.cwd() / "web" / "frontend")
    auth = WebAuth.from_settings(settings.security)
    warn_if_exposed(bind_host, auth, logger)
    info = {
        "host": bind_host,
        "port": bind_port,
        "static_dir": str(static_dir) if static_dir is not None else "not found",
        "auth": "enabled" if auth.enabled else "disabled",
    }
    return app, info


def main(argv: list[str] | None = None) -> None:
    """Run the app over uvicorn (``python -m web.webapi [--host --port --config]``)."""
    from Sprout.config.loader import load_settings
    from Sprout.orchestration.terminal.ensure import ensure_temporal
    from Sprout.storage.bootstrap import ensure_storage_sync

    parser = argparse.ArgumentParser(description="Run the SEAM_Sprout web application")
    parser.add_argument("--host", default=None, help="Bind host (default: settings.web.host)")
    parser.add_argument(
        "--port", type=int, default=None, help="Bind port (default: settings.web.port)"
    )
    parser.add_argument("--config", default=None, help="Path to sprout.toml")
    args = parser.parse_args(argv)

    ensure_temporal()
    ensure_storage_sync(load_settings(args.config))
    app, info = build_serving_app(host=args.host, port=args.port, config=args.config)
    print(f"SEAM_Sprout Web on http://{info['host']}:{info['port']}")
    print(f"static dir: {info['static_dir']}")
    print(f"api authentication: {info['auth']}")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - uvicorn ships with mcp[cli]
        raise SystemExit(f"uvicorn is not installed ({exc}); run `uv sync` first.") from exc
    uvicorn.run(app, host=info["host"], port=info["port"], log_level="info")

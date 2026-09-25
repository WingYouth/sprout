"""``sprout serve``: run the web API (application code lives in web/webapi).

The CLI is a thin Typer wrapper: the serving assembly itself lives in
``web.webapi.serve`` so the web package never imports the CLI and
``python -m web.webapi`` shares this exact path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.orchestration.terminal.ensure import ensure_temporal


def serve(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Bind host. Defaults to settings.web.host."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Bind port. Defaults to settings.web.port."),
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Serve the HTTP/WebSocket API and the built React web console.

    This command must be run from the repository root so it can import
    ``web.webapi`` and find the Vite build under ``web/frontend/dist``. It
    starts the same runtime used by ``sprout chat`` and then serves it over
    HTTP and WebSocket.
    """
    root = Path.cwd()
    ensure_temporal()
    if not (root / "web" / "webapi").is_dir():
        ui.error(
            "web/webapi not found; run `sprout serve` from the repository root.",
        )
        raise typer.Exit(code=1)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from web.webapi.serve import build_serving_app
    except ImportError as exc:
        ui.error(f"Cannot import web.webapi: {exc}")
        raise typer.Exit(code=1) from exc

    app, info = build_serving_app(host=host, port=port, config=config)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - uvicorn ships with mcp[cli]
        ui.error(
            f"uvicorn is not installed ({exc}); run `uv sync` first.", fg=typer.colors.RED
        )
        raise typer.Exit(code=1) from exc

    ui.banner(
        "SEAM_Sprout Web",
        subtitle=f"http://{info['host']}:{info['port']}",
    )
    typer.echo(ui.key_value("host", info["host"]))
    typer.echo(ui.key_value("port", info["port"]))
    typer.echo(ui.key_value("static dir", info["static_dir"]))
    typer.echo(ui.key_value("API", "HTTP + WebSocket"))
    typer.echo(ui.muted("Press Ctrl+C to stop."))
    typer.echo("")
    uvicorn.run(app, host=info["host"], port=info["port"], log_level="info")

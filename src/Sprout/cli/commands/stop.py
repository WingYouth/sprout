"""Stop long-running Sprout services."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Annotated

import typer

from Sprout.cli import ui

app = typer.Typer(help="Stop long-running Sprout services.", no_args_is_help=True)


@app.command("serve")
def stop_serve(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Web port. Defaults to settings.web.port."),
    ] = None,
) -> None:
    """Stop the Sprout web server running on the configured port."""
    from Sprout.config.loader import load_settings

    settings = load_settings()
    target_port = port or settings.web.port
    pids = _pids_listening_on(target_port)
    if not pids:
        ui.warning(f"No Sprout serve process found on port {target_port}.")
        raise typer.Exit(code=0)

    stopped: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except ProcessLookupError:
            continue
        except PermissionError:
            ui.error(f"Permission denied stopping process {pid}.")
            raise typer.Exit(code=1) from None
    ui.success(f"Stopped serve process(es): {', '.join(map(str, stopped))}")


def _pids_listening_on(port: int) -> list[int]:
    """Return PIDs bound to a local TCP port using lsof when available."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        return [int(pid) for pid in result.stdout.split() if pid.strip().isdigit()]

    # lsof is not available everywhere; pgrep can identify the CLI serve command.
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Sprout.cli.app serve"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    return [int(pid) for pid in result.stdout.split() if pid.strip().isdigit()]

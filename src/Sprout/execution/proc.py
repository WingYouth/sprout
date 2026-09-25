"""Subprocess helpers with guaranteed reclamation.

``asyncio.wait_for`` and task cancellation only stop *awaiting* a child; the OS
process keeps running. Every spawn point in the execution and sandbox layers
goes through :func:`run_capture` so a timeout, a cancellation, or any other
exception always leaves no process behind.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
from collections.abc import Mapping


def kill_tree(process: asyncio.subprocess.Process) -> None:
    """Synchronously kill ``process`` and, on Windows, its whole tree.

    Deliberately synchronous so it still works from a cancellation handler,
    where any ``await`` would immediately re-raise ``CancelledError``.
    """
    if process.returncode is not None:
        return
    if os.name == "nt":
        # ``Process.kill`` signals only the direct child; ``taskkill /T`` takes
        # the whole tree down so no grandchild outlives the request.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ("taskkill", "/F", "/T", "/PID", str(process.pid)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
    with contextlib.suppress(ProcessLookupError):
        process.kill()


async def terminate(process: asyncio.subprocess.Process) -> None:
    """Kill and reap ``process``; safe to await from a timeout/cancel handler."""
    kill_tree(process)
    with contextlib.suppress(ProcessLookupError, asyncio.CancelledError):
        await process.wait()


async def run_capture(
    program: str,
    *args: str,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    """Run ``program`` without a shell and return ``(code, stdout, stderr)``.

    The child is killed and reaped when ``timeout`` elapses, when the awaiting
    task is cancelled, or when any other exception propagates.
    """
    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        cwd=None if cwd is None else str(cwd),
        env=dict(env) if env is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if timeout is None:
            stdout, stderr = await process.communicate()
        else:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
    except BaseException:
        await terminate(process)
        raise
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )

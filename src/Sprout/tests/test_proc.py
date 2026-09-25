"""Regression tests for subprocess reclamation (audit EXEC-01 / SEC-03).

``asyncio.wait_for`` and task cancellation only stop *awaiting* a child, so
without an explicit kill a runaway process outlives the request. Each test
starts a child that writes a marker file only if it survives, then asserts the
marker never appears.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from Sprout.execution.proc import run_capture

_CHILD_LIFETIME = 2.0
_GRACE = 2.5


def _survivor_args(marker, delay: float = _CHILD_LIFETIME) -> list[str]:
    """Args for a child that writes ``marker`` only if it outlives ``delay``."""
    script = (
        "import pathlib, time\n"
        f"time.sleep({delay!r})\n"
        f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8')\n"
    )
    return ["-c", script]


async def test_run_capture_returns_streams() -> None:
    code, out, err = await run_capture(sys.executable, "-c", "print('hello')")
    assert code == 0
    assert out.strip() == "hello"
    assert err == ""


async def test_run_capture_propagates_exit_code() -> None:
    code, _out, _err = await run_capture(
        sys.executable, "-c", "import sys; sys.exit(3)"
    )
    assert code == 3


async def test_timeout_kills_child(tmp_path) -> None:
    marker = tmp_path / "after_timeout.txt"
    with pytest.raises(TimeoutError):
        await run_capture(sys.executable, *_survivor_args(marker), timeout=0.5)
    await asyncio.sleep(_GRACE)
    assert not marker.exists(), "child outlived the timeout"


async def test_cancellation_kills_child(tmp_path) -> None:
    marker = tmp_path / "after_cancel.txt"
    task = asyncio.create_task(run_capture(sys.executable, *_survivor_args(marker)))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(_GRACE)
    assert not marker.exists(), "child outlived the cancellation"

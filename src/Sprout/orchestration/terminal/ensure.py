"""Temporal startup hook used by every CLI entry point."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.orchestration.terminal.temporal import TemporalConfig


def _L(chinese: str, english: str) -> str:
    """Resolve CLI localization lazily to keep web startup import-safe."""
    from Sprout.cli.i18n import L

    return L(chinese, english)


async def ensure_temporal_async() -> TemporalConfig:
    """Require a reachable Temporal server from an async entry point."""
    from Sprout.orchestration.terminal.temporal import TemporalConfig, probe_temporal

    config = TemporalConfig.from_env()
    report: dict[str, Any] = await probe_temporal(config)
    if not report["reachable"] and _auto_start_enabled(config):
        _start_local_temporal(config)
        report = await _wait_for_temporal(config)
    if not report["reachable"]:
        raise RuntimeError(
            _L(
                f"Temporal 不可达：{config.host}。请先启动 Temporal 服务。",
                f"Temporal is unreachable at {config.host}. Start Temporal first.",
            )
        )
    if report["namespace_found"] is not True:
        raise RuntimeError(
            _L(
                f"Temporal namespace 不存在：{config.namespace}。",
                f"Temporal namespace does not exist: {config.namespace}.",
            )
        )
    if (
        report["workers"] == 0
        and _auto_start_enabled(config)
        and not _is_worker_entrypoint()
        and os.getenv("TEMPORAL_WORKER_PROCESS") != "1"
    ):
        _start_local_worker()
        report = await _wait_for_worker(config)
    return config


def _auto_start_enabled(config: TemporalConfig) -> bool:
    """Only auto-start the local dev server, never an arbitrary remote host."""
    if os.getenv("TEMPORAL_AUTO_START", "true").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return config.host in {"127.0.0.1:7233", "localhost:7233", "[::1]:7233"}


def _start_local_temporal(config: TemporalConfig) -> None:
    executable = shutil.which("temporal")
    if executable is None:
        return
    host, port = config.host.rsplit(":", 1)
    if host == "localhost":
        host = "127.0.0.1"
    _spawn_detached(
        [
            executable,
            "server",
            "start-dev",
            "--ip",
            host.strip("[]"),
            "--port",
            port,
            "--ui-port",
            os.getenv("TEMPORAL_UI_PORT", "8233"),
        ],
        os.environ.copy(),
    )


def _start_local_worker() -> None:
    child_env = os.environ.copy()
    child_env["TEMPORAL_WORKER_PROCESS"] = "1"
    # The parent has already probed Temporal through gRPC. Enable gRPC's
    # fork-safe polling mode before the worker inherits that process state.
    child_env.setdefault("GRPC_ENABLE_FORK_SUPPORT", "1")
    child_env.setdefault("GRPC_POLL_STRATEGY", "poll")
    _spawn_detached(
        [sys.executable, "-m", "Sprout", "orchestrator", "worker"],
        child_env,
    )


def _spawn_detached(argv: list[str], env: dict[str, str]) -> None:
    """Start a local service without forking a live gRPC parent process."""
    if os.name != "posix" or not hasattr(os, "posix_spawn"):
        import subprocess

        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        return

    null_fd = os.open(os.devnull, os.O_RDWR)
    try:
        os.posix_spawn(
            argv[0],
            argv,
            env,
            file_actions=[
                (os.POSIX_SPAWN_DUP2, null_fd, 0),
                (os.POSIX_SPAWN_DUP2, null_fd, 1),
                (os.POSIX_SPAWN_DUP2, null_fd, 2),
                (os.POSIX_SPAWN_CLOSE, null_fd),
            ],
            setsid=True,
        )
    finally:
        os.close(null_fd)


def _is_worker_entrypoint() -> bool:
    args = sys.argv[1:]
    return len(args) >= 2 and args[0] == "orchestrator" and args[1] == "worker"


async def _wait_for_temporal(config: TemporalConfig) -> dict[str, Any]:
    from Sprout.orchestration.terminal.temporal import probe_temporal

    for _ in range(40):
        await asyncio.sleep(0.25)
        report = await probe_temporal(config)
        if report["reachable"]:
            return report
    return report


async def _wait_for_worker(config: TemporalConfig) -> dict[str, Any]:
    from Sprout.orchestration.terminal.temporal import probe_temporal

    for _ in range(40):
        await asyncio.sleep(0.25)
        report = await probe_temporal(config)
        if report["workers"] > 0:
            return report
    return report


def ensure_temporal(*, announce: bool = True) -> TemporalConfig:
    """Require Temporal before starting a synchronous entry point."""
    config = asyncio.run(ensure_temporal_async())
    if not announce:
        return config
    print(
        _L("[temporal] 必需", "[temporal] required") + ": "
        f"host={config.host} namespace={config.namespace} "
        f"queue={config.task_queue}"
    )
    return config

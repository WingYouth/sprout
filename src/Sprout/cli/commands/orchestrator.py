"""``sprout orchestrator``: run Temporal-backed task orchestration services."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from Sprout.cli.i18n import L as _L
from Sprout.orchestration.terminal.temporal import TemporalConfig

app = typer.Typer(help="Run orchestration workers and services.", no_args_is_help=True)


@app.command("worker")
def worker(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Temporal host. Defaults to TEMPORAL_HOST."),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", help="Temporal namespace."),
    ] = None,
    task_queue: Annotated[
        str | None,
        typer.Option("--task-queue", help="Temporal task queue."),
    ] = None,
) -> None:
    """Run the Sprout Temporal worker until interrupted."""
    from Sprout.orchestration.worker import run_worker

    config = TemporalConfig.from_env()
    if host:
        config.host = host
    if namespace:
        config.namespace = namespace
    if task_queue:
        config.task_queue = task_queue
    asyncio.run(run_worker(config))


@app.command("doctor")
def doctor(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Temporal host. Defaults to TEMPORAL_HOST."),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", help="Temporal namespace."),
    ] = None,
    task_queue: Annotated[
        str | None,
        typer.Option("--task-queue", help="Temporal task queue."),
    ] = None,
) -> None:
    """Check Temporal server, namespace, and task-queue health."""
    from Sprout.orchestration.terminal.temporal import probe_temporal

    config = TemporalConfig.from_env()
    if host:
        config.host = host
    if namespace:
        config.namespace = namespace
    if task_queue:
        config.task_queue = task_queue
    report = asyncio.run(probe_temporal(config))

    typer.echo(_L("Temporal 状态", "Temporal status"))
    typer.echo(f"  Host: {report['host']}")
    typer.echo(
        _L("  可达", "  Reachable")
        + f": {_yes_no(bool(report['reachable']))}"
    )
    typer.echo(
        _L("  服务器版本", "  Server version")
        + f": {report['server_version'] or _L('未知', 'unknown')}"
    )
    typer.echo(
        _L("  命名空间", "  Namespace")
        + f": {report['namespace']} "
        + _ns_status(report["namespace_found"])
    )
    typer.echo(
        _L("  任务队列", "  Task queue")
        + f": {report['task_queue']} "
        + _L("worker 数量", "workers")
        + f"={report['workers']}"
    )
    if report["error"]:
        typer.secho(
            _L("  错误", "  Error") + f": {report['error']}",
            fg=typer.colors.YELLOW,
        )


def _yes_no(value: bool) -> str:
    return _L("是", "yes") if value else _L("否", "no")


def _ns_status(found: bool | None) -> str:
    if found is True:
        return _L("存在", "found")
    if found is False:
        return _L("不存在", "not found")
    return _L("未验证", "unverified")

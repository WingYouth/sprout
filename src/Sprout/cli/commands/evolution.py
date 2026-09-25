"""``sprout evolution``: inspect and drive the growth layer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Growth layer status and operations.", no_args_is_help=True)


def _runtime(config: str | None):
    from Sprout.config.loader import load_settings
    from Sprout.runtime.factory import create_runtime

    return create_runtime(load_settings(config))


def _manager(config: str | None):
    from Sprout.config.loader import load_settings
    from Sprout.evolution import build_candidate_manager
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    return build_candidate_manager(runtime, settings)


@app.command("trajectory-collect")
def trajectory_collect(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Collect eligible Trajectory files into new growth candidates."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.trajectory_growth import TrajectoryGrowthService
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        service = TrajectoryGrowthService(runtime.storage.metadata)
        candidates = await service.collect(
            workspace_id,
            Path(settings.storage.trajectory_dir),
        )
        if not candidates:
            typer.echo("No eligible trajectory candidates.")
            return
        for candidate in candidates:
            artifact = candidate.artifact
            name = artifact.name if artifact is not None else candidate.id[:8]
            typer.echo(f"candidate: {name} evidence={len(candidate.evidence_ids)}")

    asyncio.run(run())


@app.command("candidates")
def candidates(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """List new growth candidates."""
    manager = _manager(config)

    async def run() -> None:
        items = await manager.list_candidates()
        if not items:
            typer.echo("No growth candidates.")
            return
        for item in items:
            artifact = item.artifact
            if artifact is None:
                continue
            typer.echo(
                f"[{artifact.status.value:>7}] {artifact.id[:8]} "
                f"{artifact.kind.value}/{artifact.name} evidence={len(item.evidence_ids)}"
            )

    asyncio.run(run())


@app.command("consolidate")
def consolidate(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Deprecate older versions of the same growth artifact."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.consolidation import ArtifactConsolidator
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        changes = await ArtifactConsolidator().consolidate(runtime.storage.metadata)
        if not changes:
            typer.echo("No artifacts consolidated.")
            return
        for artifact_id, status in changes.items():
            typer.echo(f"{artifact_id[:8]} -> {status}")

    asyncio.run(run())


@app.command("maintain")
def maintain(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Advance old MONITORING/STABLE artifacts."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.maintenance import ArtifactMaintenance
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        changes = await ArtifactMaintenance().maintain(runtime.storage.metadata)
        if not changes:
            typer.echo("No artifacts changed.")
            return
        for artifact_id, status in changes.items():
            typer.echo(f"{artifact_id[:8]} -> {status}")

    asyncio.run(run())


@app.command("run-once")
def run_once(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Run one trajectory collection and candidate evaluation pass."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.automation import GrowthAutomation
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        automation = GrowthAutomation(
            runtime.storage.metadata,
            workspace_id,
            settings.storage.trajectory_dir,
            runtime=runtime,
        )
        result = await automation.run_once()
        typer.echo(
            f"candidates_collected={result['candidates_collected']} "
            f"status_changes={len(result['status_changes'])} "
            f"consolidated={len(result['consolidated'])} "
            f"maintained={len(result['maintained'])}"
        )

    asyncio.run(run())


@app.command("unified-run")
def unified_run(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Run the single trajectory-driven growth pipeline (collect + evaluate)."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.unified import UnifiedGrowthService
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        service = UnifiedGrowthService(
            runtime.storage.metadata,
            runtime.storage.observations,
        )
        trajectory_candidates = await service.collect_trajectories(
            workspace_id,
            settings.storage.trajectory_dir,
        )
        changes = await service.evaluate_all()
        typer.echo(
            f"trajectory_candidates={len(trajectory_candidates)} "
            f"status_changes={len(changes)}"
        )

    asyncio.run(run())


@app.command("schedule")
def schedule(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    interval: Annotated[float, typer.Option("--interval", help="Run interval in seconds.")] = 300.0,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Schedule periodic trajectory collection and candidate evaluation."""
    from Sprout.config.loader import load_settings
    from Sprout.evolution.automation import GrowthAutomation
    from Sprout.runtime.factory import create_runtime
    from Sprout.scheduler.scheduler import Scheduler

    settings = load_settings(config)
    runtime = create_runtime(settings)
    if runtime.storage.metadata is None:
        typer.secho("MetadataStore is not configured.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def run() -> None:
        automation = GrowthAutomation(
            runtime.storage.metadata,
            workspace_id,
            settings.storage.trajectory_dir,
            runtime=runtime,
        )
        scheduler = Scheduler()
        automation.attach(scheduler, interval_seconds=interval)
        scheduler.start()
        typer.echo(f"Scheduled growth automation every {interval} seconds. Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await scheduler.stop()

    asyncio.run(run())


@app.command("evaluate-candidates")
def evaluate_candidates(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Run hard gates and utility scoring on candidates."""
    manager = _manager(config)

    async def run() -> None:
        changes = await manager.evaluate_all()
        if not changes:
            typer.echo("No candidates changed.")
            return
        for artifact_id, status in changes.items():
            typer.echo(f"{artifact_id[:8]} -> {status}")

    asyncio.run(run())


@app.command("approve-candidate")
def approve_candidate(
    artifact_id: Annotated[str, typer.Argument(help="Artifact id or prefix.")],
    by: Annotated[str, typer.Option("--by", help="Approver identity.")] = "cli",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Approve a validated growth candidate."""
    manager = _manager(config)

    async def run() -> None:
        artifact = await manager.approve(artifact_id, decided_by=by)
        typer.echo(f"published: {artifact.kind.value}/{artifact.name} v{artifact.version}")

    asyncio.run(run())


@app.command("reject-candidate")
def reject_candidate(
    artifact_id: Annotated[str, typer.Argument(help="Artifact id or prefix.")],
    reason: Annotated[str, typer.Option("--reason", help="Rejection reason.")] = "",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Reject a validated growth candidate."""
    manager = _manager(config)

    async def run() -> None:
        artifact = await manager.reject(artifact_id, reason=reason)
        typer.echo(f"rejected: {artifact.kind.value}/{artifact.name}")

    asyncio.run(run())

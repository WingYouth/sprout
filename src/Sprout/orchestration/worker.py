"""Temporal worker entry point for Sprout orchestration."""

from __future__ import annotations

from Sprout.orchestration.terminal.temporal import TemporalConfig


async def run_worker(config: TemporalConfig | None = None) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from Sprout.config.loader import load_settings
    from Sprout.orchestration.temporal_workflows import (
        SproutExecutionWorkflow,
        SproutGatewayWorkflow,
        SproutGrowthWorkflow,
        SproutTaskWorkflow,
        run_growth_automation,
        run_sprout_node,
        set_activity_runtime,
    )
    from Sprout.runtime.factory import create_runtime

    config = config or TemporalConfig.from_env()
    settings = load_settings()
    from Sprout.storage.bootstrap import ensure_storage_ready

    await ensure_storage_ready(settings)
    runtime = create_runtime(settings)
    await runtime.start()
    set_activity_runtime(runtime)
    client = await Client.connect(config.host, namespace=config.namespace)
    try:
        worker = Worker(
            client,
            task_queue=config.task_queue,
            workflows=[
                SproutExecutionWorkflow,
                SproutGatewayWorkflow,
                SproutGrowthWorkflow,
                SproutTaskWorkflow,
            ],
            activities=[run_growth_automation, run_sprout_node],
        )
        await worker.run()
    finally:
        await runtime.stop()

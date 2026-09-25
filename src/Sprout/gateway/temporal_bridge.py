"""Submit long gateway work to Temporal for durability."""

from __future__ import annotations

import os
from typing import Any


async def submit_gateway_workflow(payload: dict[str, Any]) -> None:
    host = os.getenv("TEMPORAL_HOST")
    if not host:
        return
    from temporalio.client import Client

    from Sprout.orchestration.terminal.temporal import TemporalConfig

    config = TemporalConfig.from_env()
    client = await Client.connect(config.host, namespace=config.namespace)
    await client.start_workflow(
        "SproutGatewayWorkflow",
        payload,
        id=f"gateway-{payload.get('transport', 'unknown')}-{payload.get('id', 'task')}",
        task_queue=config.task_queue,
    )

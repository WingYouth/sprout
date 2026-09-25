"""Web bridge for submitting Temporal workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request


def create_temporal_routes() -> list:
    from starlette.routing import Route

    async def submit(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        workflow = data.get("workflow")
        args = data.get("args", [])
        if not isinstance(workflow, str) or not workflow:
            return JSONResponse({"error": "'workflow' is required"}, status_code=400)
        if not isinstance(args, list):
            return JSONResponse({"error": "'args' must be an array"}, status_code=400)

        from temporalio.client import Client

        from Sprout.orchestration.terminal.temporal import TemporalConfig

        config = TemporalConfig.from_env()
        client = await Client.connect(config.host, namespace=config.namespace)
        handle = await client.start_workflow(
            workflow,
            args,
            id=f"web-{data.get('id', 'task')}",
            task_queue=config.task_queue,
        )
        return JSONResponse({"workflow_id": handle.id})

    return [Route("/api/temporal/submit", submit, methods=["POST"])]

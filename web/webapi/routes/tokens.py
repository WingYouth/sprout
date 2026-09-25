"""Token usage endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from web.webapi.database import WebDatabase


def create_token_routes(database: WebDatabase) -> list:
    from starlette.routing import Route

    from Sprout.llm.usage import get_usage_recorder

    recorder = get_usage_recorder()

    async def token_endpoint(request: Request) -> JSONResponse:
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        records = recorder.list_usage(limit=max(1, min(limit, 500)))
        return JSONResponse({"summary": recorder.summary(), "records": records})

    return [Route("/api/tokens", token_endpoint, methods=["GET"])]

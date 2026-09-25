"""Health endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from Sprout.runtime.runtime import Runtime


def create_health_route(runtime: Runtime):
    async def health(request: Request) -> JSONResponse:
        info = runtime.describe()
        return JSONResponse(
            {
                "status": "ok",
                "name": info.name,
                "version": info.version,
                "default_agent": info.default_agent,
            }
        )

    return health

"""Settings endpoints: effective runtime config and web preferences."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from Sprout.config.settings import Settings
    from web.webapi.database import WebDatabase


def create_settings_routes(
    settings: Settings | None,
    database: WebDatabase,
) -> list:
    from starlette.routing import Route

    from Sprout.config.loader import load_settings, mask_settings

    effective = settings or load_settings()

    async def get_settings(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                # Masked: the effective config carries DSN passwords and the
                # whole policy boundary, and this endpoint is a display view.
                "settings": mask_settings(effective),
                "preferences": await database.get_preferences(),
                "config_path": _find_config_path(),
            }
        )

    async def put_preferences(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(data, dict):
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        for key, value in data.items():
            if not isinstance(key, str) or not key.strip():
                return JSONResponse({"error": "preference keys must be strings"}, status_code=400)
            if value is not None and not isinstance(value, (str, int, float, bool, list, dict)):
                return JSONResponse(
                    {"error": f"unsupported preference value for {key!r}"},
                    status_code=400,
                )
            await database.set_preference(key, value)
        return JSONResponse({"preferences": await database.get_preferences()})

    async def delete_preference(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        await database.set_preference(key, None)
        return JSONResponse({"ok": True, "key": key})

    return [
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/preferences", put_preferences, methods=["PUT"]),
        Route("/api/preferences/{key}", delete_preference, methods=["DELETE"]),
    ]


def _find_config_path() -> str | None:
    """Return the first real sprout.toml the loader would discover."""
    env_path = os.environ.get("SPROUT_CONFIG")
    candidates = [
        Path(env_path) if env_path else None,
        Path("sprout.toml"),
        Path.home() / ".sprout" / "sprout.toml",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return str(candidate.resolve())
    return None

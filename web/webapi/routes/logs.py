"""Unified log endpoints backed by SQLite stores."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from Sprout.llm.usage import get_usage_recorder

if TYPE_CHECKING:
    from starlette.requests import Request

    from web.webapi.database import WebDatabase


def create_log_routes(database: WebDatabase) -> list:
    from starlette.routing import Route

    async def logs_endpoint(request: Request) -> JSONResponse:
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 500))
        records = await _collect_logs(database, limit)
        return JSONResponse(
            {
                "count": len(records),
                "records": records,
                "categories": _categories(records),
            }
        )

    return [Route("/api/logs", logs_endpoint, methods=["GET"])]


async def _collect_logs(database: WebDatabase, limit: int) -> list[dict]:
    recorder = get_usage_recorder()
    route_rows = await database.recent_requests(limit)
    task_rows = (await database.list_tasks())[-limit:]
    model_rows = recorder.list_usage(limit)

    records: list[dict] = []
    for row in route_rows:
        status = row.get("status_code")
        records.append(
            {
                "id": f"route-{row.get('id')}",
                "category": "failure" if status and int(status) >= 400 else "route",
                "type": "route",
                "ts": row.get("ts"),
                "summary": f"{row.get('method')} {row.get('route')}",
                "status": status,
                "detail": f"{row.get('duration_ms')} ms",
                "session_id": row.get("session_id"),
                "user_id": row.get("user_id"),
            }
        )
    for row in task_rows:
        records.append(
            {
                "id": f"task-{row.get('id')}",
                "category": "task",
                "type": "task",
                "ts": row.get("updated_at") or row.get("created_at"),
                "summary": row.get("title"),
                "status": row.get("status"),
                "detail": row.get("priority"),
                "session_id": None,
                "user_id": None,
            }
        )
    for row in model_rows:
        records.append(
            {
                "id": f"model-{row.get('id')}",
                "category": "model",
                "type": "model",
                "ts": row.get("ts"),
                "summary": f"{row.get('provider') or '-'} / {row.get('model') or '-'}",
                "status": "ok",
                "detail": (
                    f"input={row.get('input_tokens')} "
                    f"output={row.get('output_tokens')} "
                    f"total={row.get('total_tokens')}"
                ),
                "session_id": None,
                "user_id": None,
            }
        )
    records.sort(key=lambda item: item.get("ts") or "", reverse=True)
    return records[:limit]


def _categories(records: list[dict]) -> list[dict]:
    labels = {
        "route": "路由日志",
        "model": "模型调用",
        "task": "任务日志",
        "failure": "失败日志",
    }
    counts: dict[str, int] = {}
    for record in records:
        counts[record["category"]] = counts.get(record["category"], 0) + 1
    return [
        {"key": key, "label": labels.get(key, key), "count": counts.get(key, 0)}
        for key in labels
    ]

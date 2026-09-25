"""Task CRUD endpoints used by the task board and task manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from web.webapi.database import WebDatabase

STATUSES = {"todo", "doing", "done"}
PRIORITIES = {"low", "medium", "high"}


def create_task_routes(database: WebDatabase) -> list:
    from starlette.routing import Route

    async def list_tasks(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        tasks = await database.list_tasks()
        if status:
            tasks = [task for task in tasks if task["status"] == status]
        return JSONResponse({"tasks": tasks})

    async def create_task(request: Request) -> JSONResponse:
        payload = await _read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            return JSONResponse({"error": "'title' must be a non-empty string"}, status_code=400)

        try:
            fields = _task_fields(payload, creating=True)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        task = await database.create_task(title=title.strip(), **fields)
        return JSONResponse(task, status_code=201)

    async def update_task(request: Request) -> JSONResponse:
        task_id = request.path_params["task_id"]
        payload = await _read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        if not await database.get_task(task_id):
            return JSONResponse({"error": "task not found"}, status_code=404)

        try:
            fields = _task_fields(payload, creating=False)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        task = await database.update_task(task_id, **fields)
        return JSONResponse(task or {"error": "task not found"}, status_code=200)

    async def delete_task(request: Request) -> JSONResponse:
        task_id = request.path_params["task_id"]
        deleted = await database.delete_task(task_id)
        if not deleted:
            return JSONResponse({"error": "task not found"}, status_code=404)
        return JSONResponse({"ok": True, "id": task_id})

    return [
        Route("/api/tasks", list_tasks, methods=["GET"]),
        Route("/api/tasks", create_task, methods=["POST"]),
        Route("/api/tasks/{task_id}", update_task, methods=["PATCH"]),
        Route("/api/tasks/{task_id}", delete_task, methods=["DELETE"]),
    ]


async def _read_json(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    return data


def _task_fields(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """Validate and normalize task fields shared by create and update."""
    allowed = {
        "description",
        "status",
        "priority",
        "tags",
        "assignee",
        "due_at",
    }
    unknown = set(payload) - allowed - {"title"}
    if unknown:
        raise ValueError(f"unknown task field(s): {', '.join(sorted(unknown))}")

    fields: dict[str, Any] = {}
    if "description" in payload:
        description = payload["description"]
        if description is not None and not isinstance(description, str):
            raise ValueError("'description' must be a string or null")
        fields["description"] = description or ""

    if "status" in payload:
        status = payload["status"]
        if status not in STATUSES:
            raise ValueError(f"'status' must be one of {', '.join(sorted(STATUSES))}")
        fields["status"] = status
    elif creating:
        fields["status"] = "todo"

    if "priority" in payload:
        priority = payload["priority"]
        if priority not in PRIORITIES:
            raise ValueError(f"'priority' must be one of {', '.join(sorted(PRIORITIES))}")
        fields["priority"] = priority
    elif creating:
        fields["priority"] = "medium"

    if "tags" in payload:
        tags = payload["tags"]
        if tags is None:
            fields["tags"] = []
        elif isinstance(tags, list) and all(isinstance(tag, str) for tag in tags):
            fields["tags"] = tags
        else:
            raise ValueError("'tags' must be an array of strings or null")

    if "assignee" in payload:
        assignee = payload["assignee"]
        if assignee is not None and not isinstance(assignee, str):
            raise ValueError("'assignee' must be a string or null")
        fields["assignee"] = assignee

    if "due_at" in payload:
        due_at = payload["due_at"]
        if due_at is not None and not isinstance(due_at, str):
            raise ValueError("'due_at' must be an ISO date string or null")
        fields["due_at"] = due_at

    return fields

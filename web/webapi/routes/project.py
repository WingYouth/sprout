"""Project Runtime HTTP routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.gateway.project_gateway import ProjectGateway
from Sprout.runtime.runtime import Runtime


def _task_payload(task) -> dict:
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "instruction": task.instruction,
        "source": task.source,
        "status": task.status.value,
        "phases": [phase.value for phase in task.phases],
        "metadata": dict(task.metadata),
        "created_at": task.created_at.isoformat(),
    }


def create_project_routes(runtime: Runtime) -> list[Route]:
    gateway = ProjectGateway(runtime, transport="web", default_user="web-user")

    async def list_workspaces(request: Request) -> JSONResponse:
        workspaces = await gateway.list_workspaces()
        return JSONResponse(
            [
                {
                    "id": item.id,
                    "kind": item.kind.value,
                    "root": str(item.root),
                }
                for item in workspaces
            ]
        )

    async def open_workspace(request: Request) -> JSONResponse:
        data = await request.json()
        path = data.get("path") if isinstance(data, dict) else None
        if not isinstance(path, str):
            return JSONResponse({"error": "path is required"}, status_code=400)
        workspace = await gateway.open_workspace(path)
        return JSONResponse(
            {
                "id": workspace.id,
                "kind": workspace.kind.value,
                "root": str(workspace.root),
            }
        )

    async def create_task(request: Request) -> JSONResponse:
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse({"error": "expected object"}, status_code=400)
        task = await gateway.create_task(
            data["workspace_id"],
            data["instruction"],
        )
        return JSONResponse({"id": task.id, "status": task.status.value})

    async def list_tasks(request: Request) -> JSONResponse:
        workspace_id = request.query_params.get("workspace_id")
        tasks = await runtime.list_tasks(workspace_id)
        return JSONResponse({"tasks": [_task_payload(task) for task in tasks]})

    async def analyze_workspace(request: Request) -> JSONResponse:
        analysis = await gateway.analyze_workspace(request.path_params["workspace_id"])
        return JSONResponse(
            {
                "workspace_id": request.path_params["workspace_id"],
                "nodes": len(analysis.graph.nodes),
                "edges": len(analysis.graph.edges),
                "knowledge": len(analysis.knowledge.items),
            }
        )

    async def run_task(request: Request) -> JSONResponse:
        task_id = request.path_params["task_id"]
        result = await gateway.run_task(task_id)
        return JSONResponse(
            {
                "task_id": result.task_id,
                "status": result.status,
            }
        )

    async def list_changes(request: Request) -> JSONResponse:
        task_id = request.path_params["task_id"]
        proposals = await gateway.list_changes(task_id)
        return JSONResponse(
            [
                {
                    "id": item.id,
                    "status": item.status.value,
                    "risk": item.risk,
                    "files_changed": list(item.files_changed),
                }
                for item in proposals
            ]
        )

    async def show_proposal(request: Request) -> JSONResponse:
        proposal = await gateway.show_proposal(request.path_params["proposal_id"])
        return JSONResponse(
            {
                "id": proposal.id,
                "task_id": proposal.task_id,
                "status": proposal.status.value,
                "risk": proposal.risk,
                "files_changed": list(proposal.files_changed),
                "diffs": [diff.diff_text for diff in proposal.diffs],
            }
        )

    async def approve_proposal(request: Request) -> JSONResponse:
        proposal = await gateway.find_proposal(request.path_params["proposal_id"])
        updated = await gateway.approve_proposal(proposal.id)
        return JSONResponse({"id": updated.id, "status": updated.status.value})

    async def reject_proposal(request: Request) -> JSONResponse:
        proposal = await gateway.find_proposal(request.path_params["proposal_id"])
        data = await request.json() if await request.body() else {}
        reason = data.get("reason", "") if isinstance(data, dict) else ""
        updated = await gateway.reject_proposal(proposal.id, reason=reason)
        return JSONResponse({"id": updated.id, "status": updated.status.value})

    async def apply_proposal(request: Request) -> JSONResponse:
        proposal = await gateway.find_proposal(request.path_params["proposal_id"])
        result = await gateway.apply_proposal(proposal.id)
        return JSONResponse(
            {
                "proposal_id": result.proposal_id,
                "applied": result.applied,
                "reason": result.reason,
            }
        )

    return [
        Route("/api/project/workspaces", list_workspaces, methods=["GET"]),
        Route("/api/project/workspaces", open_workspace, methods=["POST"]),
        Route(
            "/api/project/workspaces/{workspace_id}/analyze",
            analyze_workspace,
            methods=["POST"],
        ),
        Route("/api/project/tasks", list_tasks, methods=["GET"]),
        Route("/api/project/tasks", create_task, methods=["POST"]),
        Route("/api/project/tasks/{task_id}/run", run_task, methods=["POST"]),
        Route("/api/project/tasks/{task_id}/changes", list_changes, methods=["GET"]),
        Route("/api/project/proposals/{proposal_id}", show_proposal, methods=["GET"]),
        Route("/api/project/proposals/{proposal_id}/approve", approve_proposal, methods=["POST"]),
        Route("/api/project/proposals/{proposal_id}/reject", reject_proposal, methods=["POST"]),
        Route("/api/project/proposals/{proposal_id}/apply", apply_proposal, methods=["POST"]),
    ]

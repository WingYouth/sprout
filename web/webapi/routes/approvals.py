"""Approval decision routes (AUTHZ §5.2).

The web API is one of exactly two places a human decision can be recorded (the
other is the CLI). MCP stays request-only: an external agent may ask for
approval but can never grant one to itself.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.runtime.runtime import Runtime
from Sprout.security.approval import ApprovalStatus

from ..auth import caller_user_id


def _serialize(record) -> dict:
    return {
        "id": record.id,
        "tool": record.tool,
        "status": record.status.value,
        "task_id": record.task_id,
        "session_id": record.session_id,
        "approval_class": record.approval_class,
        "source": record.source,
        "resource_scope": record.resource_scope,
        "action_summary": record.action_summary,
        "requested_by": record.requested_by,
        "decided_by": record.decided_by,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
        "decided_at": record.decided_at.isoformat() if record.decided_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


def create_approval_routes(runtime: Runtime) -> list[Route]:
    async def list_approvals(request: Request) -> JSONResponse:
        raw_status = request.query_params.get("status")
        status = None
        if raw_status:
            try:
                status = ApprovalStatus(raw_status)
            except ValueError:
                return JSONResponse({"error": f"unknown status: {raw_status}"}, status_code=400)
        records = await runtime.list_approvals(status)
        backlog = await runtime.approval_backlog_age()
        return JSONResponse(
            {
                "approvals": [_serialize(record) for record in records],
                "oldest_pending_age_seconds": backlog,
            }
        )

    async def pending_approvals(request: Request) -> JSONResponse:
        records = await runtime.pending_approvals()
        return JSONResponse({"approvals": [_serialize(record) for record in records]})

    async def decide_approval(request: Request) -> JSONResponse:
        approval_id = request.path_params["approval_id"]
        data = await request.json() if await request.body() else {}
        if not isinstance(data, dict) or "approve" not in data:
            return JSONResponse({"error": "field 'approve' is required"}, status_code=400)
        # The audit trail has to name whoever actually decided (AUTHZ §5.2), so
        # this comes from the authenticated caller rather than a body field.
        decided_by = caller_user_id(request, str(data.get("decided_by") or "web-user"))
        reason = data.get("reason")
        try:
            record = await runtime.decide_approval(
                approval_id,
                bool(data["approve"]),
                decided_by=decided_by,
                reason=str(reason) if reason is not None else None,
                channel="web",
            )
        except LookupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse(_serialize(record))

    async def sweep_approvals(request: Request) -> JSONResponse:
        swept = await runtime.sweep_approvals()
        return JSONResponse({"swept": swept})

    return [
        Route("/api/approvals", list_approvals, methods=["GET"]),
        Route("/api/approvals/pending", pending_approvals, methods=["GET"]),
        Route("/api/approvals/sweep", sweep_approvals, methods=["POST"]),
        Route("/api/approvals/{approval_id}/decide", decide_approval, methods=["POST"]),
    ]

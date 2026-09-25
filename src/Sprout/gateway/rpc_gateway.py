"""JSON-RPC gateway over the daemon project facade."""

from __future__ import annotations

from typing import Any

from Sprout.gateway.daemon_gateway import DaemonGateway
from Sprout.gateway.rpc_errors import RPCErrorCode
from Sprout.runtime.runtime import Runtime


class RPCGateway:
    """Routes JSON-RPC-style requests to project operations."""

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._daemon = DaemonGateway(runtime)

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        try:
            result = await self._dispatch(method, params)
        except KeyError as exc:
            return self._error(request_id, RPCErrorCode.INVALID_PARAMS, f"Missing {exc}")
        except LookupError as exc:
            return self._error(request_id, RPCErrorCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            return self._error(request_id, RPCErrorCode.INVALID_STATE, str(exc))
        except Exception as exc:  # noqa: BLE001 - RPC must always return JSON
            return self._error(request_id, RPCErrorCode.INTERNAL_ERROR, str(exc))
        return {"id": request_id, "result": result}

    async def _dispatch(self, method: str, params: dict[str, Any]):
        if method == "workspace.open":
            workspace = await self._daemon.open_workspace(params["path"])
            return {"id": workspace.id, "kind": workspace.kind.value}
        if method == "workspace.list":
            return [
                {"id": item.id, "kind": item.kind.value, "root": str(item.root)}
                for item in await self._daemon.list_workspaces()
            ]
        if method == "task.create":
            task = await self._daemon.create_task(
                params["workspace_id"],
                params["instruction"],
            )
            return {"id": task.id, "status": task.status.value}
        if method == "task.run":
            response = await self._daemon.run_task(params["task_id"])
            return {
                "task_id": response.task_id,
                "status": response.status,
            }
        if method == "task.submit":
            task = await self._runtime.get_task(params["task_id"])
            if task is None:
                raise LookupError(f"Task not found: {params['task_id']}")
            await self._runtime.submit_task(task)
            return {"task_id": task.id, "queued": True}
        if method == "task.changes":
            proposals = await self._daemon.list_changes(params["task_id"])
            return [
                {
                    "id": item.id,
                    "status": item.status.value,
                    "risk": item.risk,
                    "files_changed": list(item.files_changed),
                }
                for item in proposals
            ]
        if method == "proposal.show":
            proposal = await self._runtime.find_change_proposal(params["proposal_id"])
            if proposal is None:
                raise LookupError(f"Proposal not found: {params['proposal_id']}")
            return {
                "id": proposal.id,
                "task_id": proposal.task_id,
                "status": proposal.status.value,
                "risk": proposal.risk,
                "files_changed": list(proposal.files_changed),
                "diffs": [diff.diff_text for diff in proposal.diffs],
            }
        if method == "proposal.approve":
            proposal = await self._runtime.find_change_proposal(params["proposal_id"])
            if proposal is None:
                raise LookupError(f"Proposal not found: {params['proposal_id']}")
            updated = await self._runtime.approve_change_proposal(
                proposal.id,
                decided_by="rpc",
            )
            return {"id": updated.id, "status": updated.status.value}
        if method == "proposal.reject":
            proposal = await self._runtime.find_change_proposal(params["proposal_id"])
            if proposal is None:
                raise LookupError(f"Proposal not found: {params['proposal_id']}")
            updated = await self._runtime.reject_change_proposal(
                proposal.id,
                reason=params.get("reason", ""),
            )
            return {"id": updated.id, "status": updated.status.value}
        if method == "proposal.apply":
            proposal = await self._runtime.find_change_proposal(params["proposal_id"])
            if proposal is None:
                raise LookupError(f"Proposal not found: {params['proposal_id']}")
            result = await self._runtime.apply_change_proposal(proposal.id)
            return {
                "proposal_id": result.proposal_id,
                "applied": result.applied,
                "reason": result.reason,
            }
        if method == "proposal.rollback":
            proposal = await self._runtime.find_change_proposal(params["proposal_id"])
            if proposal is None:
                raise LookupError(f"Proposal not found: {params['proposal_id']}")
            result = await self._runtime.rollback_change_proposal(proposal.id)
            return {
                "proposal_id": result.proposal_id,
                "applied": result.applied,
                "reason": result.reason,
            }
        if method == "trajectory.query":
            events = await self._runtime.read_trajectory(params["task_id"])
            return [
                {
                    "id": event.id,
                    "name": event.name,
                    "task_id": event.task_id,
                    "payload": dict(event.payload),
                }
                for event in events
            ]
        return self._error(None, RPCErrorCode.METHOD_NOT_FOUND, f"Unsupported method: {method}")

    @staticmethod
    def _error(request_id, code: RPCErrorCode, message: str) -> dict[str, Any]:
        return {
            "id": request_id,
            "error": {
                "code": code.value,
                "message": message,
            },
        }

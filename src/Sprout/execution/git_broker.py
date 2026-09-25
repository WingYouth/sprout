"""Policy-controlled Git operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from Sprout.execution.git_env import git_args, git_env
from Sprout.execution.models import GitResult
from Sprout.execution.policy_emit import emit_policy_decision
from Sprout.execution.proc import run_capture
from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.approval import ApprovalManager
from Sprout.security.engine import PolicyEngine
from Sprout.task.models import DelegationScope
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace

if TYPE_CHECKING:
    from Sprout.events import EventBus

#: The tool that exposes these operations to the model. Approvals are requested
#: and stored under the *tool* name by :class:`~Sprout.tools.executor.ToolExecutor`,
#: so the broker has to consume them under the same name. Checking with
#: ``ActionType.GIT_COMMIT.value`` (``git.commit``) instead never matched,
#: silently turning the broker's gate into "always refuse, even when approved".
GIT_WRITE_TOOL = "git_write"


class GitBroker:
    """Executes read-only and approved Git state changes."""

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        approvals: ApprovalManager | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._policy = policy
        self._approvals = approvals
        self._events = events

    async def status(
        self, workspace: Workspace, *, scope: DelegationScope | None = None
    ) -> GitResult:
        decision = await self._decide(workspace, ActionType.GIT_STATUS, {}, "", scope)
        if decision is not AccessDecision.ALLOW:
            return GitResult(action="status", allowed=False, reason=decision.value)
        output = await self._run(workspace, "status", "--porcelain")
        return GitResult(action="status", output=output)

    async def diff(
        self, workspace: Workspace, *, scope: DelegationScope | None = None
    ) -> GitResult:
        decision = await self._decide(workspace, ActionType.GIT_DIFF, {}, "", scope)
        if decision is not AccessDecision.ALLOW:
            return GitResult(action="diff", allowed=False, reason=decision.value)
        return GitResult(
            action="diff",
            output=await self._run(workspace, "diff", "--no-color", "--no-ext-diff"),
        )

    async def log(self, workspace: Workspace, limit: int = 20) -> GitResult:
        decision = await self._decide(workspace, ActionType.GIT_LOG, {"limit": limit})
        if decision is not AccessDecision.ALLOW:
            return GitResult(action="log", allowed=False, reason=decision.value)
        return GitResult(
            action="log",
            output=await self._run(workspace, "log", "--oneline", "-n", str(limit)),
        )

    async def branch(self, workspace: Workspace) -> GitResult:
        decision = await self._decide(workspace, ActionType.GIT_BRANCH, {})
        if decision is not AccessDecision.ALLOW:
            return GitResult(action="branch", allowed=False, reason=decision.value)
        return GitResult(
            action="branch",
            output=await self._run(workspace, "branch", "--all", "-vv"),
        )

    async def add(self, workspace: Workspace, files: tuple[str, ...] = ()) -> GitResult:
        arguments = {"files": list(files)}
        decision = await self._decide(workspace, ActionType.GIT_ADD, arguments)
        if decision is not AccessDecision.ALLOW:
            return GitResult(action="add", allowed=False, reason=decision.value)
        await self._run(workspace, "add", *(files or ("-A",)))
        return GitResult(action="add")

    async def commit(
        self,
        workspace: Workspace,
        message: str,
        *,
        files: tuple[str, ...] = (),
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> GitResult:
        arguments = {"message": message, "files": list(files)}
        decision = await self._decide(workspace, ActionType.GIT_COMMIT, arguments, task_id, scope)
        if decision is AccessDecision.REQUIRE_APPROVAL:
            if self._approvals is None or not await self._approvals.is_approved(
                GIT_WRITE_TOOL,
                arguments,
                task_id=task_id,
            ):
                return GitResult(
                    action="commit",
                    allowed=False,
                    reason="Git commit requires approval",
                )
        elif decision is not AccessDecision.ALLOW:
            return GitResult(action="commit", allowed=False, reason=decision.value)
        await self._run(workspace, "add", *(files or ("-A",)))
        output = await self._run(workspace, "commit", "-m", message)
        return GitResult(action="commit", output=output)

    async def push(
        self,
        workspace: Workspace,
        remote: str = "origin",
        branch: str | None = None,
        *,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> GitResult:
        arguments = {"remote": remote, "branch": branch}
        decision = await self._decide(workspace, ActionType.GIT_PUSH, arguments, task_id, scope)
        if decision is AccessDecision.REQUIRE_APPROVAL:
            if self._approvals is None or not await self._approvals.is_approved(
                GIT_WRITE_TOOL,
                arguments,
                task_id=task_id,
            ):
                return GitResult(action="push", allowed=False, reason="Git push requires approval")
        elif decision is not AccessDecision.ALLOW:
            return GitResult(action="push", allowed=False, reason=decision.value)
        args = ["push", remote]
        if branch:
            args.append(branch)
        return GitResult(action="push", output=await self._run(workspace, *args))

    async def pull(
        self,
        workspace: Workspace,
        remote: str = "origin",
        branch: str | None = None,
        *,
        task_id: str = "",
    ) -> GitResult:
        arguments = {"remote": remote, "branch": branch}
        decision = await self._decide(workspace, ActionType.GIT_PULL, arguments, task_id)
        if decision is AccessDecision.REQUIRE_APPROVAL:
            if self._approvals is None or not await self._approvals.is_approved(
                GIT_WRITE_TOOL,
                arguments,
                task_id=task_id,
            ):
                return GitResult(action="pull", allowed=False, reason="Git pull requires approval")
        elif decision is not AccessDecision.ALLOW:
            return GitResult(action="pull", allowed=False, reason=decision.value)
        args = ["pull", "--ff-only", remote]
        if branch:
            args.append(branch)
        return GitResult(action="pull", output=await self._run(workspace, *args))

    async def _decide(
        self,
        workspace: Workspace,
        action: ActionType,
        arguments: dict,
        task_id: str = "",
        scope: DelegationScope | None = None,
    ) -> AccessDecision:
        resource = ResourceRef(
            workspace_id=workspace.id,
            path=str(workspace.root),
            kind=ResourceKind.CONFIG,
        )
        request = ActionRequest(
            task_id=task_id,
            action=action,
            resource=resource,
            arguments=arguments,
            scope=scope if scope is not None else DelegationScope(),
        )
        decision = self._policy.decide(request)
        await emit_policy_decision(self._events, request, decision)
        return decision.decision

    @staticmethod
    async def _run(workspace: Workspace, *args: str) -> str:
        code, stdout, stderr = await run_capture(
            "git",
            *git_args("-C", str(workspace.root), *args),
            env=git_env(),
        )
        if code != 0:
            detail = stderr.strip()
            raise RuntimeError(detail or f"git command failed with code {code}")
        return stdout

"""Node execution: one class owning every execution-graph node branch.

The Runtime builds a :class:`NodeExecutor` and hands the orchestrator a handler
closure, so the graph runner never sees brokers, prompts, or output clamping
(Herness spec 7.2 for the minimal node context, 8.3 for approval parking).
"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from Sprout.agent.router import AgentRouter
from Sprout.artifacts.models import ArtifactKind
from Sprout.context.builder import ContextBuilder
from Sprout.execution.apply import ApplyBroker
from Sprout.execution.change import ChangeProposalBuilder
from Sprout.execution.file_broker import FileBroker
from Sprout.execution.models import (
    ChangeProposalStatus,
    ProcessResult,
    SandboxRef,
    TestResult,
)
from Sprout.execution.process_broker import ProcessBroker
from Sprout.execution.sandbox_tool import (
    SandboxApplyPatchTool,
    SandboxEditTool,
    SandboxGitTool,
    SandboxListTool,
    SandboxReadTool,
    SandboxSearchTool,
    SandboxWriteTool,
)
from Sprout.llm.language import detect_language
from Sprout.message.models import Message
from Sprout.orchestration.models import ExecutionNode, NodeType
from Sprout.sandbox.git_worktree import GitWorktreeSandbox
from Sprout.skills.models import Skill
from Sprout.skills.registry import SkillRegistry
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.task.models import Task
from Sprout.tools.registry import ToolRegistry
from Sprout.trajectory.models import ArtifactSnapshot, TrajectoryEvent
from Sprout.trajectory.recorder import JsonlTrajectoryRecorder
from Sprout.workspace.models import ReadPlan, Workspace, WorkspaceKind
from Sprout.workspace.read_broker import ReadBroker

# Clamping keeps node metadata small and avoids persisting whole files.
_NODE_OUTPUT_LIMIT = 4_000
_RESOURCE_PREVIEW_CHARS = 1_500
# Verification output is persisted into node metadata, so it is clamped harder
# than the agent's own answer.
_TEST_OUTPUT_CHARS = 2_000


def verification_status(*, executed: int, failed: int, withheld: int) -> str:
    """Classify an evaluation round from its command outcomes.

    Three outcomes, not two. A command the policy withheld never ran, so
    calling it a failure says something false about the change — and it hid the
    fact that evaluation was executing nothing at all while reporting "failed"
    every round, which also made the verify-loop retry a condition that
    retrying cannot change (another agent round does not grant approval).

    A real failure still outranks a withheld command: that change is known bad,
    whatever else did not get to run.
    """
    if executed == 0:
        return "no_test_commands"
    if withheld == executed:
        return "not_verified"
    if failed:
        return "failed"
    if withheld:
        # Some passed, some never ran: those passes are not a verified change.
        return "partially_verified"
    return "passed"


def _clamp_test_output(stdout: str, stderr: str, error: str | None) -> str:
    """Build one bounded output blob for a persisted test/build result."""
    blocks: list[str] = []
    if stdout.strip():
        blocks.append(stdout.strip())
    if stderr.strip():
        blocks.append("[stderr]\n" + stderr.strip())
    if not blocks and error:
        blocks.append(error)
    return "\n".join(blocks)[:_TEST_OUTPUT_CHARS]


def _test_result_payload(result: TestResult) -> dict[str, Any]:
    """JSON-safe shape; node metadata is persisted, so no dataclasses travel."""
    return {
        "name": result.name,
        "passed": result.passed,
        "output": result.output,
        "duration_ms": result.duration_ms,
        # Round-trips, or every reconstructed result would default to
        # "executed" and the apply gate would lose the distinction again.
        "executed": result.executed,
    }


def _test_result_from_payload(payload: Mapping[str, Any]) -> TestResult:
    try:
        duration = float(payload.get("duration_ms") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return TestResult(
        name=str(payload.get("name", "")),
        passed=bool(payload.get("passed")),
        output=str(payload.get("output", "")),
        duration_ms=duration,
        # Absent means an older payload, which predates withheld commands and
        # therefore always executed.
        executed=bool(payload.get("executed", True)),
    )


class NodeExecutor:
    """Executes one node: reads resources, runs the agent, gates, applies.

    The executor owns the node-type branches and the prompts handed to the
    agent; the Runtime only assembles it and forwards a handler to the
    orchestrator.
    """

    def __init__(
        self,
        *,
        metadata: MetadataStore,
        router: AgentRouter | None,
        contexts: ContextBuilder,
        tools: ToolRegistry,
        skills: SkillRegistry,
        read_broker: ReadBroker,
        file_broker: FileBroker,
        process_broker: ProcessBroker,
        apply_broker: ApplyBroker,
        changes: Any | None = None,
    ) -> None:
        self._metadata = metadata
        self._router = router
        self._contexts = contexts
        self._tools = tools
        self._skills = skills
        self._read_broker = read_broker
        self._file_broker = file_broker
        self._process_broker = process_broker
        self._apply_broker = apply_broker
        self._changes = changes
        self._change_builder = ChangeProposalBuilder()

    def handler(
        self, task: Task, workspace: Workspace, read_plan: ReadPlan
    ) -> Callable[[ExecutionNode], Awaitable[Any]]:
        """Build the callable the orchestrator invokes per node."""

        async def execute(node: ExecutionNode) -> Any:
            return await self.execute_node(node, workspace, read_plan, task)

        return execute

    async def execute_node(
        self,
        node: ExecutionNode,
        workspace: Workspace,
        read_plan: ReadPlan,
        task: Task,
    ) -> Any:
        """Run one node and return its persisted output."""
        if node.type is NodeType.READ:
            return await self._read(workspace, read_plan, task)
        if node.type is NodeType.PLAN:
            return await self._plan(node, workspace, task)
        if node.type is NodeType.SUBTASK:
            return await self._subtask(node, workspace, task)
        if node.type is NodeType.AGENT:
            return await self._agent(node, workspace, task)
        if node.type is NodeType.SANDBOX:
            return await self._sandbox(workspace)
        if node.type is NodeType.EVALUATION:
            return await self._evaluation(node, workspace, task)
        if node.type is NodeType.APPROVAL:
            return await self._approval(workspace, task)
        if node.type is NodeType.APPLY:
            return await self._apply(workspace, task)
        return None

    async def pin_snapshot(
        self,
        recorder: JsonlTrajectoryRecorder,
        artifact_snapshot: ArtifactSnapshot | None,
        task_id: str,
    ) -> Skill | None:
        """Register the pinned artifact version so the run stays reproducible."""
        if artifact_snapshot is None:
            return None
        artifact = await self._metadata.get_artifact(artifact_snapshot.artifact_id)
        if artifact is None or artifact.version != artifact_snapshot.artifact_version:
            return None
        await recorder.record(
            TrajectoryEvent(
                name="artifact.pinned",
                task_id=task_id,
                payload={
                    "artifact_id": artifact.id,
                    "artifact_version": artifact.version,
                },
            )
        )
        if artifact.kind is not ArtifactKind.SKILL:
            return None
        pinned = Skill(
            name=artifact.name,
            version=artifact.version,
            instructions=artifact.content,
            required_tools=(),
            enabled=True,
        )
        self._skills.register(pinned)
        return pinned

    # -- node branches -----------------------------------------------------
    async def _read(
        self, workspace: Workspace, read_plan: ReadPlan, task: Task
    ) -> list[dict]:
        # The task's delegation scope travels with every read (AUTHZ §2.2); a
        # channel that granted read-only access must not get more than that.
        results = await self._read_broker.read(
            workspace, read_plan, scope=task.delegation_scope
        )
        return [
            {
                "path": item.resource.path,
                "decision": item.decision.value,
                "content": item.content,
                "error": item.error,
            }
            for item in results
        ]

    async def _agent(
        self, node: ExecutionNode, workspace: Workspace, task: Task
    ) -> dict:
        nodes = await self._metadata.list_execution_nodes(task.id)
        sandbox_tools: list = []
        sandbox_ref = self._sandbox_ref_from(self._output_for(nodes, NodeType.SANDBOX))
        if sandbox_ref is not None:
            available_tools = {
                "sandbox_write_file": SandboxWriteTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                "sandbox_read_file": SandboxReadTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                "sandbox_edit_file": SandboxEditTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                "sandbox_apply_patch": SandboxApplyPatchTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                "sandbox_list_files": SandboxListTool(sandbox_ref),
                "sandbox_search": SandboxSearchTool(sandbox_ref),
                "sandbox_git_inspect": SandboxGitTool(sandbox_ref),
            }
            tool_names = set(node.metadata.get("tool_names") or ())
            sandbox_tools = (
                [
                    tool
                    for name, tool in available_tools.items()
                    if name in tool_names
                ]
                if tool_names
                else list(available_tools.values())
            )
        resources = self._resources(self._output_for(nodes, NodeType.READ), workspace)
        feedback = self._previous_evaluation_feedback(node, nodes)
        plan_output = self._output_for(nodes, NodeType.PLAN)
        plan = (
            str(plan_output.get("plan", ""))
            if isinstance(plan_output, dict)
            else ""
        )
        findings = self._subtask_findings(nodes)
        if self._router is None:
            raise RuntimeError("No agent router configured")
        message = Message(
            content=self._agent_prompt(
                task, workspace, resources, feedback, plan, findings
            ),
            channel="task",
            user_id=task.actor.user_id,
            metadata={
                "task_id": task.id,
                "node_id": node.id,
                "resource_paths": [item["path"] for item in resources],
                "response_language": str(
                    task.metadata.get("response_language")
                    or task.metadata.get("cli_language")
                    or detect_language(task.instruction)
                ),
            },
        )
        # Node context: only this node's resources and tools, no inherited history.
        context = self._contexts.build_node_context(
            user_id=task.actor.user_id,
            node_id=node.id,
            tools={tool.spec.name: tool for tool in sandbox_tools},
            files=tuple(item["path"] for item in resources),
            metadata={
                "task_id": task.id,
                "resources": tuple(resources),
                "task_budget": {
                    "max_model_calls": task.budget.max_model_calls,
                    "max_tool_calls": task.budget.max_tool_calls,
                    "max_tokens": task.budget.max_tokens,
                },
            },
        )
        # No global register/unregister: the node's tools travel in
        # ``context.tools`` and the executor dispatches from there, so two
        # nodes running at once cannot unregister each other's tools.
        agent = self._router.route(message)
        result = await agent.run(message, context)
        return {
            "content": result.content[:_NODE_OUTPUT_LIMIT],
            "node_id": node.id,
            "resources": [item["path"] for item in resources],
        }

    async def _plan(
        self, node: ExecutionNode, workspace: Workspace, task: Task
    ) -> dict:
        """Run a read-only planning pass before the first edit round."""
        nodes = await self._metadata.list_execution_nodes(task.id)
        sandbox_ref = self._sandbox_ref_from(self._output_for(nodes, NodeType.SANDBOX))
        plan_tools: list = []
        if sandbox_ref is not None:
            plan_tools = [
                SandboxReadTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                SandboxListTool(sandbox_ref),
                SandboxSearchTool(sandbox_ref),
                SandboxGitTool(sandbox_ref),
            ]
        resources = self._resources(self._output_for(nodes, NodeType.READ), workspace)
        if self._router is None:
            raise RuntimeError("No agent router configured")
        message = Message(
            content=self._plan_prompt(task, workspace, resources),
            channel="task",
            user_id=task.actor.user_id,
            metadata={
                "task_id": task.id,
                "node_id": node.id,
                "resource_paths": [item["path"] for item in resources],
            },
        )
        context = self._contexts.build_node_context(
            user_id=task.actor.user_id,
            node_id=node.id,
            tools={tool.spec.name: tool for tool in plan_tools},
            files=tuple(item["path"] for item in resources),
            metadata={
                "task_id": task.id,
                "resources": tuple(resources),
            },
        )
        agent = self._router.route(message)
        result = await agent.run(message, context)
        return {
            "plan": result.content[:_NODE_OUTPUT_LIMIT],
            "node_id": node.id,
        }

    async def _subtask(
        self, node: ExecutionNode, workspace: Workspace, task: Task
    ) -> dict:
        """Investigate one plan step and report evidence; never edits.

        Read-only by construction: the tool set is the planning set, so a
        subtask cannot write even if the model asks it to. Its output is
        evidence for the edit round, not a change.
        """
        metadata = node.metadata
        description = str(metadata.get("description") or "").strip()
        if not description:
            return {"status": "skipped", "reason": "empty step description"}

        nodes = await self._metadata.list_execution_nodes(task.id)
        sandbox_ref = self._sandbox_ref_from(self._output_for(nodes, NodeType.SANDBOX))
        tools: list = []
        if sandbox_ref is not None:
            tools = [
                SandboxReadTool(
                    sandbox_ref,
                    self._file_broker,
                    scope=task.delegation_scope,
                    task_id=task.id,
                ),
                SandboxListTool(sandbox_ref),
                SandboxSearchTool(sandbox_ref),
                SandboxGitTool(sandbox_ref),
            ]

        # Prefer the step's own target files; fall back to the task's read plan
        # so a step without paths still has something to reason about.
        target_paths = [
            str(path) for path in metadata.get("target_paths") or () if str(path).strip()
        ]
        all_resources = self._resources(
            self._output_for(nodes, NodeType.READ), workspace
        )
        if target_paths:
            wanted = set(target_paths)
            resources = tuple(
                item for item in all_resources if item["path"] in wanted
            ) or all_resources
        else:
            resources = all_resources

        if self._router is None:
            raise RuntimeError("No agent router configured")
        message = Message(
            content=self._subtask_prompt(description, metadata, resources),
            channel="task",
            user_id=task.actor.user_id,
            metadata={
                "task_id": task.id,
                "node_id": node.id,
                "resource_paths": [item["path"] for item in resources],
            },
        )
        context = self._contexts.build_node_context(
            user_id=task.actor.user_id,
            node_id=node.id,
            tools={tool.spec.name: tool for tool in tools},
            files=tuple(item["path"] for item in resources),
            metadata={
                "task_id": task.id,
                "resources": tuple(resources),
            },
        )
        agent = self._router.route(message)
        result = await agent.run(message, context)
        return {
            "node_id": node.id,
            "index": metadata.get("index"),
            "kind": metadata.get("kind", "other"),
            "description": description,
            "findings": result.content[:_NODE_OUTPUT_LIMIT],
        }

    async def _sandbox(self, workspace: Workspace) -> dict:
        if workspace.kind is not WorkspaceKind.GIT_REPOSITORY:
            return {
                "status": "not_applicable",
                "reason": "workspace is not a Git repository",
            }
        ref = await GitWorktreeSandbox(workspace).create()
        return {
            "id": ref.id,
            "kind": ref.kind,
            "root": str(ref.root),
            "worktree_ref": ref.worktree_ref,
        }

    async def _evaluation(
        self, node: ExecutionNode, workspace: Workspace, task: Task
    ) -> dict:
        """Run the manifest's test and build commands against the sandbox.

        Verification used to run with ``cwd=workspace.root`` while every change
        the task made lived in the sandbox worktree, so a green result proved
        nothing about the diff waiting for approval. It now runs where the agent
        wrote. ``build_commands`` was carried in node metadata and never read.
        """
        nodes = await self._metadata.list_execution_nodes(task.id)
        sandbox_ref = self._sandbox_ref_from(self._output_for(nodes, NodeType.SANDBOX))
        cwd = sandbox_ref.root if sandbox_ref is not None else workspace.root

        planned: list[tuple[str, tuple[str, ...]]] = [
            ("test", tuple(str(command).split()))
            for command in node.metadata.get("test_commands", ())
        ]
        planned.extend(
            ("build", tuple(str(command).split()))
            for command in node.metadata.get("build_commands", ())
        )
        # Requirement-specific acceptance commands from the strategy layer,
        # keyed by their criterion kind so the results read as "database/schema
        # failed" rather than "test #4 failed".
        for item in node.metadata.get("verification_commands", ()):
            if not isinstance(item, dict):
                continue
            command = str(item.get("command") or "").strip()
            if not command:
                continue
            planned.append((str(item.get("kind") or "acceptance"), tuple(command.split())))
        planned.extend(await self._static_check_commands(workspace, sandbox_ref))
        if not planned:
            planned = self._fallback_verification(workspace)
        attempts = max(1, int(node.metadata.get("verification_attempts", 1)))

        records: list[dict] = []
        test_results: list[TestResult] = []
        failed: list[str] = []
        withheld: list[str] = []
        pending_approvals: list[str] = []
        for kind, parts in planned:
            if not parts:
                continue
            outcome = await self._run_verification_command(
                workspace, parts, cwd, task, attempts
            )
            passed = outcome.allowed and outcome.exit_code == 0
            name = f"{kind}: {' '.join(parts)}"
            test_results.append(
                TestResult(
                    name=name,
                    passed=passed,
                    output=_clamp_test_output(
                        outcome.stdout, outcome.stderr, outcome.error
                    ),
                    duration_ms=outcome.duration_ms,
                    # Distinguishes "ran and failed" from "never ran", which the
                    # apply gate needs to decide about.
                    executed=outcome.allowed,
                )
            )
            records.append(
                {
                    "kind": kind,
                    "command": list(parts),
                    "exit_code": outcome.exit_code,
                    "allowed": outcome.allowed,
                    "allowlisted": outcome.allowlisted,
                    "passed": passed,
                    "attempts": attempts,
                    "error": outcome.error,
                    # Set when the command is parked on a human grant, so the
                    # node can wait for it instead of concluding.
                    "approval_id": outcome.approval_id,
                }
            )
            if outcome.needs_approval:
                pending_approvals.append(outcome.approval_id)
            if not outcome.allowed:
                withheld.append(name)
            elif not passed:
                failed.append(name)

        status = verification_status(
            executed=len(test_results),
            failed=len(failed),
            withheld=len(withheld),
        )
        return {
            "test_commands": [
                " ".join(command) for kind, command in planned if kind == "test"
            ],
            "build_commands": [
                " ".join(command) for kind, command in planned if kind == "build"
            ],
            "check_commands": [
                " ".join(command) for kind, command in planned if kind == "check"
            ],
            "cwd": str(cwd),
            "sandbox_root": str(sandbox_ref.root) if sandbox_ref is not None else None,
            "results": records,
            "test_results": [_test_result_payload(item) for item in test_results],
            "status": status,
            "failed_commands": failed,
            # Carried separately so an approver can tell "this failed" from
            # "nobody checked": the two need different decisions.
            "unverified_commands": withheld,
            # Commands parked on a grant. The node WAITS rather than
            # concluding, because "completed" is terminal and would make the
            # approval pointless: resume skips completed nodes, so the granted
            # command would never re-run and the change would land on a
            # verification result that predates the grant.
            "waiting": bool(pending_approvals),
            "pending_approvals": list(dict.fromkeys(pending_approvals)),
        }

    async def _run_verification_command(
        self,
        workspace: Workspace,
        parts: tuple[str, ...],
        cwd: Path,
        task: Task,
        attempts: int,
    ) -> ProcessResult:
        """Run one verification command, retrying transient failures."""
        outcome = None
        for attempt in range(attempts):
            outcome = await self._process_broker.run(
                workspace,
                parts,
                cwd=cwd,
                task_id=task.id,
                scope=task.delegation_scope,
                command_origin="manifest",
                # Carried so a withheld command can be attributed to the task
                # and its source, which is what decides whether a human can be
                # asked at all.
                source=str(task.actor.source or "interactive"),
                requested_by=task.actor.user_id or "system",
                resource_scope=task.workspace_id,
            )
            if outcome.allowed and outcome.exit_code == 0:
                break
            if attempt + 1 < attempts and not outcome.allowed:
                break
        return outcome

    async def _static_check_commands(
        self,
        workspace: Workspace,
        sandbox_ref: SandboxRef | None,
    ) -> list[tuple[str, tuple[str, ...]]]:
        """Build changed-file scoped lint/typecheck commands when tools exist."""
        if sandbox_ref is None or workspace.kind is not WorkspaceKind.GIT_REPOSITORY:
            return []
        changed = await GitWorktreeSandbox(workspace).changed_files(sandbox_ref)
        manifest = workspace.manifest
        languages = set(manifest.detected_languages) if manifest is not None else set()
        commands: list[tuple[str, tuple[str, ...]]] = []

        python_files = tuple(path for path in changed if path.endswith(".py"))
        if python_files:
            commands.append(("check", ("python", "-m", "compileall", "-q", *python_files)))
            if shutil.which("ruff"):
                commands.append(("check", ("ruff", "check", *python_files)))

        if languages & {"typescript", "node"}:
            ts_files = tuple(
                path for path in changed if path.endswith((".ts", ".tsx"))
            )
            if ts_files and shutil.which("tsc") and (sandbox_ref.root / "tsconfig.json").exists():
                commands.append(("check", ("tsc", "--noEmit")))
        return commands

    @staticmethod
    def _fallback_verification(
        workspace: Workspace,
    ) -> list[tuple[str, tuple[str, ...]]]:
        """Offer a cheap static check when the manifest found no test/build."""
        manifest = workspace.manifest
        languages = set(manifest.detected_languages) if manifest is not None else set()
        if "python" in languages:
            return [("check", ("python", "-m", "compileall", "-q", "."))]
        return []

    async def _approval(self, workspace: Workspace, task: Task) -> dict:
        nodes = await self._metadata.list_execution_nodes(task.id)
        sandbox_ref = self._sandbox_ref_from(
            self._output_for(nodes, NodeType.SANDBOX)
        )
        existing = await self._metadata.list_change_proposals(task.id)
        if existing:
            # Approval is resumable: never mint a second proposal for the same
            # task when the graph is continued after a human decision.
            proposal = existing[0]
            return {
                "proposal_id": proposal.id,
                "status": proposal.status.value,
                "files_changed": list(proposal.files_changed),
                "waiting": proposal.status is not ChangeProposalStatus.APPROVED,
            }

        evaluation = self._output_for(nodes, NodeType.EVALUATION)
        test_results = self._test_results_from(evaluation)
        # Commands the policy withheld. Distinct from a failure: nobody looked.
        # They must be removed from ``failed`` before it is used for risk
        # grading and the apply gate, or an unverified change gets treated as a
        # known-bad one and blocks a merge that was never actually tested.
        unverified = (
            list(evaluation.get("unverified_commands") or [])
            if isinstance(evaluation, dict)
            else []
        )
        withheld = set(unverified)
        failed = [
            item.name
            for item in test_results
            if not item.passed and item.name not in withheld
        ]

        diffs = []
        files_changed: tuple[str, ...] = ()
        if sandbox_ref is not None:
            sandbox = GitWorktreeSandbox(workspace)
            diff = await sandbox.diff(sandbox_ref)
            if diff.diff_text:
                diffs.append(diff)
            files_changed = await sandbox.changed_files(sandbox_ref)

        if not files_changed and not diffs:
            # A turn that produced no file changes has nothing to apply, so it
            # must not park on a change proposal. Read-only and conversational
            # tasks finish here and return the agent's answer instead.
            return {
                "status": "no_changes",
                "files_changed": [],
                "test_status": (
                    evaluation.get("status") if isinstance(evaluation, dict) else None
                ),
                "failed_commands": failed,
                "unverified_commands": unverified,
            }

        proposal = self._change_builder.build(
            task_id=task.id,
            sandbox_ref=sandbox_ref,
            files_changed=files_changed,
            test_results=tuple(test_results),
            diffs=tuple(diffs),
            # A change whose verification failed is not a "medium risk" change:
            # the approver has to see that, and ``ChangeProposalService.apply``
            # refuses to land it without an explicit override.
            #
            # Unverified is deliberately *not* upgraded to high: the diff was
            # never judged, so calling it high would overstate what is known.
            # It rides in metadata instead, where the approver reads it.
            risk="high" if failed else "medium",
            rollback_plan="",
        )
        proposal = replace(
            proposal,
            rollback_plan=(
                f"Roll back the applied commit for change proposal {proposal.id} "
                f"with `sprout project rollback {proposal.id}`. "
                f"Files: {', '.join(files_changed) or '(none)'}."
            ),
            metadata={
                "summary": task.instruction,
                # An approver must be able to tell "this passed", "this failed"
                # and "nobody checked" apart — they are different decisions.
                "verification": {
                    "status": (
                        evaluation.get("status")
                        if isinstance(evaluation, dict)
                        else None
                    ),
                    "failed_commands": failed,
                    "unverified_commands": unverified,
                },
            },
        )
        await self._metadata.save_change_proposal(proposal)
        # Park the graph until a human grants or rejects the proposal.
        return {
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "files_changed": list(files_changed),
            "test_status": (
                evaluation.get("status") if isinstance(evaluation, dict) else None
            ),
            "failed_commands": failed,
            "unverified_commands": unverified,
            "waiting": True,
        }

    async def _apply(self, workspace: Workspace, task: Task) -> dict:
        proposals = await self._metadata.list_change_proposals(task.id)
        if not proposals:
            return {"status": "no_change_proposal"}
        proposal = proposals[0]
        if proposal.status is not ChangeProposalStatus.APPROVED:
            return {
                "proposal_id": proposal.id,
                "status": proposal.status.value,
                "waiting": True,
            }
        if self._changes is not None:
            result = await self._changes.apply(
                proposal.id,
                allow_failing_tests=bool(
                    proposal.metadata.get("allow_failing_tests_approved")
                ),
            )
        else:
            result = await self._apply_broker.apply(
                proposal, workspace, scope=task.delegation_scope
            )
        if not result.applied:
            # The graph must not report success for a change that never
            # landed. It used to: a refused apply returned a normal payload,
            # the node was marked COMPLETED, and the task finished as
            # ``completed`` while the workspace was untouched — so a caller
            # that trusted the status believed the code was in.
            #
            # Raising marks the node (and the task) FAILED with the reason,
            # which is both true and recoverable: FAILED -> RETRYING is a legal
            # transition, so landing it later with an override still works.
            raise RuntimeError(
                f"Apply did not land change proposal {result.proposal_id}: "
                f"{result.reason or 'no reason given'}"
            )
        return {
            "proposal_id": result.proposal_id,
            "applied": result.applied,
            "reason": result.reason,
        }

    # -- output helpers ----------------------------------------------------
    @staticmethod
    def _output_for(
        nodes: list[ExecutionNode], node_type: NodeType
    ) -> dict | list | None:
        """The most recent *real* output of ``node_type``.

        Placeholder outputs are skipped. The verify-loop marks the rounds it
        does not run as SKIPPED with ``{"skipped": True}``, and taking the last
        match blindly meant downstream readers got an empty placeholder instead
        of the evaluation that actually ran — the approval node was building
        change proposals from a skipped node, so the verification status never
        reached the approver.
        """
        for node in reversed(nodes):
            if node.type is not node_type:
                continue
            output = node.metadata.get("output")
            if not isinstance(output, dict | list):
                continue
            if isinstance(output, dict) and output.get("skipped"):
                continue
            return output
        return None

    @staticmethod
    def _subtask_findings(nodes: list[ExecutionNode]) -> tuple[dict[str, Any], ...]:
        """Every SUBTASK node's output, in step order.

        Unlike :meth:`_output_for`, which returns the last match for a single
        node type, this collects them all: the agent's value from decomposition
        is seeing every step's evidence at once.
        """
        found: list[dict[str, Any]] = []
        for node in nodes:
            if node.type is not NodeType.SUBTASK:
                continue
            output = node.metadata.get("output")
            if isinstance(output, dict) and output.get("findings"):
                found.append(output)
        found.sort(key=lambda item: item.get("index") or 0)
        return tuple(found)

    @staticmethod
    def _sandbox_ref_from(output: Any) -> SandboxRef | None:
        if not isinstance(output, dict) or "id" not in output:
            return None
        return SandboxRef(
            id=output["id"],
            kind=output["kind"],
            root=Path(output["root"]),
            worktree_ref=output.get("worktree_ref"),
        )

    @staticmethod
    def _test_results_from(evaluation: Any) -> tuple[TestResult, ...]:
        """Rebuild the persisted EVALUATION payload into ``TestResult`` objects."""
        if not isinstance(evaluation, dict):
            return ()
        payload = evaluation.get("test_results")
        if not isinstance(payload, list):
            return ()
        return tuple(
            _test_result_from_payload(item)
            for item in payload
            if isinstance(item, Mapping)
        )

    @staticmethod
    def _resources(
        read_output: Any, workspace: Workspace
    ) -> tuple[dict[str, str], ...]:
        """Turn READ node output into bounded resource previews for one node."""
        if not isinstance(read_output, list):
            return ()
        items: list[dict[str, str]] = []
        for entry in read_output:
            if not isinstance(entry, dict):
                continue
            raw_path = str(entry.get("path", ""))
            if not raw_path:
                continue
            decision = str(entry.get("decision", ""))
            want_content = decision not in {"deny", "AccessDecision.DENY"}
            content = ""
            if want_content:
                content = str(entry.get("content") or "")[:_RESOURCE_PREVIEW_CHARS]
            items.append(
                {
                    "path": NodeExecutor._display_path(raw_path, workspace),
                    "decision": decision,
                    "content": content,
                }
            )
        return tuple(items)

    @staticmethod
    def _display_path(raw_path: str, workspace: Workspace) -> str:
        try:
            return (
                Path(raw_path)
                .resolve()
                .relative_to(Path(workspace.root).resolve())
                .as_posix()
            )
        except (ValueError, OSError):
            return raw_path

    @staticmethod
    def _agent_prompt(
        task: Task,
        workspace: Workspace,
        resources: tuple[dict[str, str], ...],
        feedback: dict[str, Any] | None = None,
        plan: str = "",
        findings: tuple[dict[str, Any], ...] = (),
    ) -> str:
        """Compose the node-level instruction: task plus only its own resources."""
        lines = [task.instruction]
        lines.extend(
            [
                "",
                "For code changes, prefer sandbox_apply_patch with a complete unified diff "
                "so the edit is reviewable and follows the standard patch workflow. Use "
                "sandbox_write_file for creating a complete new file, or the focused "
                "sandbox_edit_file tool for a small exact replacement when a patch is "
                "not practical. Never use process execution to write project files.",
            ]
        )
        if plan:
            lines.extend(["", "Plan from the planning step:", plan])
        if findings:
            lines.extend(["", "Findings from the plan's investigation steps:"])
            for item in findings:
                kind = str(item.get("kind") or "other")
                lines.append(f"- [{kind}] {item.get('description', '')}")
                body = str(item.get("findings") or "").strip()
                if body:
                    lines.append(f"    {body.replace(chr(10), chr(10) + '    ')}")
        if feedback:
            lines.extend(
                [
                    "",
                    "Previous verification feedback:",
                    f"- status: {feedback.get('status', 'unknown')}",
                ]
            )
            failed = feedback.get("failed_commands") or []
            if failed:
                lines.append(f"- failed commands: {', '.join(map(str, failed))}")
            results = feedback.get("results") or []
            for item in results:
                if not isinstance(item, dict):
                    continue
                command = " ".join(map(str, item.get("command", [])))
                lines.append(
                    f"- {command}: exit {item.get('exit_code', '?')} "
                    f"(passed={item.get('passed', False)})"
                )
            test_results = feedback.get("test_results") or []
            for item in test_results:
                if not isinstance(item, dict):
                    continue
                output = str(item.get("output", "")).strip()
                if output:
                    lines.append(f"- {item.get('name', 'test')}: {output}")
            lines.append(
                "If the previous attempt failed verification, inspect the sandbox, "
                "fix the change, and re-run the relevant check before finishing."
            )
        lines.extend(["", "Resources allowed for this step:"])
        if not resources:
            lines.append("- (none)")
        for item in resources:
            lines.append(f"- {item['path']} [{item['decision']}]")
            if item["content"]:
                indented = item["content"].replace("\n", "\n    ")
                lines.append(f"    {indented}")
        return "\n".join(lines)

    @staticmethod
    def _plan_prompt(
        task: Task,
        workspace: Workspace,
        resources: tuple[dict[str, str], ...],
    ) -> str:
        """Ask for a concrete, reviewable plan before any code is written."""
        lines = [
            "Produce a concrete implementation plan for the task below.",
            "Do not modify files yet. Inspect the allowed resources if needed, "
            "then list the exact files, symbols, and edits you intend to make.",
            "",
            "Task:",
            task.instruction,
            "",
            "Resources allowed for planning:",
        ]
        if not resources:
            lines.append("- (none)")
        for item in resources:
            lines.append(f"- {item['path']} [{item['decision']}]")
            if item["content"]:
                indented = item["content"].replace("\n", "\n    ")
                lines.append(f"    {indented}")
        return "\n".join(lines)

    @staticmethod
    def _subtask_prompt(
        description: str,
        metadata: dict,
        resources: tuple[dict[str, str], ...],
    ) -> str:
        """Ask one plan step to gather evidence, explicitly not to edit."""
        lines = [
            "Investigate one step of an implementation plan and report what you "
            "find. This is a read-only pass: do NOT modify any files.",
            "",
            "Step:",
            description,
        ]
        acceptance = str(metadata.get("acceptance") or "").strip()
        if acceptance:
            lines.extend(["", "Done when:", acceptance])
        targets = [str(path) for path in metadata.get("target_paths") or ()]
        if targets:
            lines.extend(["", "Files this step concerns:"])
            lines.extend(f"- {path}" for path in targets)
        lines.extend(
            [
                "",
                "Report the exact files, symbols, and edits the next step should "
                "make. Be concrete: name the functions and the lines that matter.",
                "",
                "Resources available:",
            ]
        )
        if not resources:
            lines.append("- (none)")
        for item in resources:
            lines.append(f"- {item['path']} [{item['decision']}]")
            if item["content"]:
                indented = item["content"].replace("\n", "\n    ")
                lines.append(f"    {indented}")
        return "\n".join(lines)

    @staticmethod
    def _previous_evaluation_feedback(
        node: ExecutionNode, nodes: list[ExecutionNode]
    ) -> dict[str, Any] | None:
        """Return the evaluation output that precedes this agent in the graph."""
        previous_id = node.metadata.get("previous_evaluation_node_id")
        if not isinstance(previous_id, str):
            return None
        for candidate in nodes:
            if candidate.id != previous_id:
                continue
            output = candidate.metadata.get("output")
            return output if isinstance(output, dict) else None
        return None

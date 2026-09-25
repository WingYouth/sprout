"""``sprout run``: autonomous, looping project automation from the current directory."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated, Any

import typer

from Sprout.cli import ui
from Sprout.cli.approval_prompt import (
    APPROVE,
    APPROVE_SIMILAR,
    QUIT,
    REJECT,
    ask_approval_sync,
)
from Sprout.cli.diff import render_diff
from Sprout.execution.models import ChangeProposalStatus
from Sprout.gateway.identity import Principal
from Sprout.llm.messages import LLMMessage
from Sprout.task.models import TaskStatus
from Sprout.workspace.models import WorkspaceManifest

_PIPELINE = "scan -> strategy -> coding -> validation -> integrate -> verify -> confirm"
_FALLBACK_INSTRUCTION = (
    "Review the project and implement the most impactful correctness, "
    "maintainability, or testability improvement you can find, adding or "
    "updating tests for the change."
)
_AUTONOMOUS_SYSTEM = (
    "You are the autonomous engineering loop for a software project. "
    "Given a project scan and the previous change, propose exactly one "
    "concrete, small next improvement as a single imperative instruction. "
    "Return only the instruction text, with no preamble and no Markdown."
)


def _manifest_brief(manifest: WorkspaceManifest | None) -> str:
    if manifest is None:
        return "no manifest available"
    parts: list[str] = []
    if manifest.detected_languages:
        parts.append("languages=" + ",".join(manifest.detected_languages))
    if manifest.framework_hints:
        parts.append("frameworks=" + ",".join(manifest.framework_hints))
    if manifest.entry_points:
        parts.append("entry_points=" + ",".join(manifest.entry_points))
    if manifest.test_commands:
        parts.append("test=" + "; ".join(manifest.test_commands))
    if manifest.build_commands:
        parts.append("build=" + "; ".join(manifest.build_commands))
    return "; ".join(parts) or "no manifest details"


def _clean_instruction(text: str) -> str:
    """Strip fences, quotes, and leading labels from a model's proposal."""
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip().strip("`\"'")
    text = re.sub(
        r"^(next improvement|improvement|instruction|task)\s*[:：-]\s*",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    return text.strip()


async def _derive_next_instruction(runtime: Any, workspace: Any, previous: str) -> str | None:
    """Ask the configured model for one next improvement from a fresh scan."""
    if getattr(runtime.models, "default_name", "echo") == "echo":
        return None
    manifest = await runtime.scan_workspace(workspace.id)
    prompt = (
        f"Project scan: {_manifest_brief(manifest)}\n"
        f"Previous change: {previous or '(none)'}\n"
        "Propose the next single improvement."
    )
    try:
        response = await runtime.models.default().chat(
            [
                LLMMessage.system(_AUTONOMOUS_SYSTEM),
                LLMMessage.user(prompt),
            ]
        )
    except Exception:
        return None
    cleaned = _clean_instruction(response.text)
    return cleaned or None


def _ask_approval(
    message: str, *, allow_similar: bool = False, allow_quit: bool = False
) -> str | None:
    """Ask the operator to decide one pending approval.

    Returns the shared CLI approval decision. A non-interactive terminal
    returns ``None`` so the loop leaves the decision parked instead of guessing.
    """
    return ask_approval_sync(
        message, allow_similar=allow_similar, allow_quit=allow_quit
    )


def _proposal_prompt(proposal: Any) -> str:
    files = getattr(proposal, "files_changed", ()) or ()
    metadata = getattr(proposal, "metadata", {}) or {}
    summary = str(metadata.get("summary") or "")
    verification = metadata.get("verification") or {}
    verification_status = (
        str(verification.get("status"))
        if isinstance(verification, dict) and verification.get("status")
        else ""
    )
    detail: list[str] = []
    if files:
        names = ", ".join(files[:4])
        if len(files) > 4:
            names += ", ..."
        detail.append(f"files: {names}")
    if verification_status:
        detail.append(f"verification: {verification_status}")
    prefix = f"Apply change proposal {str(getattr(proposal, 'id', ''))[:8]}"
    if summary:
        prefix += f": {summary[:80]}"
    return prefix + ("  " + " | ".join(detail) if detail else "")


async def _resolve_approvals(runtime: Any, task: Any) -> tuple[Any, bool]:
    """Interactively decide the approvals blocking ``task``.

    Returns ``(task, quit)``. Verification-command grants are decided first
    because they gate the evaluation node; change proposals are decided after
    the task reaches them. ``quit`` is True when the operator chose to stop.
    """
    if getattr(task, "status", None) is not TaskStatus.WAITING_APPROVAL:
        return task, False

    try:
        records = [
            record
            for record in await runtime.pending_approvals()
            if getattr(record, "task_id", "") == task.id
        ]
    except Exception:
        records = []
    for record in records:
        summary = getattr(record, "action_summary", "") or getattr(record, "action_hash", "")
        choice = _ask_approval(
            f"Approve {getattr(record, 'tool', 'action')}? {summary}",
            allow_similar=bool(getattr(record, "approval_class", "")),
            allow_quit=True,
        )
        if choice == QUIT:
            return task, True
        if choice == APPROVE_SIMILAR:
            record.single_use = False
            await runtime.approvals.store.save_approval(record)
        if choice in (APPROVE, APPROVE_SIMILAR, REJECT):
            await runtime.decide_approval(
                record.id, choice != REJECT, decided_by="cli"
            )

    task = await runtime.get_task(task.id) or task
    if getattr(task, "status", None) is not TaskStatus.WAITING_APPROVAL:
        return task, False

    try:
        proposals = await runtime.list_change_proposals(task.id)
    except Exception:
        proposals = []
    pending = [
        proposal
        for proposal in proposals
        if getattr(proposal, "status", None) is ChangeProposalStatus.PENDING
    ]
    for proposal in pending:
        for diff in getattr(proposal, "diffs", ()) or ():
            render_diff(diff.path, diff.diff_text)
        choice = _ask_approval(_proposal_prompt(proposal), allow_quit=True)
        if choice == QUIT:
            return task, True
        if choice == APPROVE:
            await runtime.approve_change_proposal(proposal.id, decided_by="cli")
        elif choice == REJECT:
            await runtime.reject_change_proposal(proposal.id)

    task = await runtime.get_task(task.id) or task
    return task, False


async def _whole_project_verify(runtime: Any, task: Any) -> list[dict[str, Any]] | None:
    """Run the workspace's test commands against the integrated tree."""
    try:
        manifest = await runtime.scan_workspace(task.workspace_id)
    except Exception:
        return None
    commands = manifest.test_commands if manifest is not None else ()
    if not commands:
        return None
    outcomes: list[dict[str, Any]] = []
    for command in commands:
        parts = tuple(str(command).split())
        if not parts:
            continue
        try:
            outcome = await runtime.run_task_process(task.id, parts)
        except Exception as exc:
            outcomes.append(
                {
                    "command": command,
                    "passed": False,
                    "withheld": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        outcomes.append(
            {
                "command": command,
                "passed": bool(outcome.allowed and outcome.exit_code == 0),
                "withheld": bool(outcome.needs_approval),
            }
        )
    return outcomes


def _print_cycle(
    cycle: int,
    task: Any,
    instruction: str,
    verification: list[dict[str, Any]] | None,
) -> None:
    status = getattr(task, "status", None)
    status_value = status.value if status is not None else "unknown"
    typer.echo(ui.text(f"cycle {cycle}", bold=True))
    typer.echo(ui.key_value("instruction", instruction))
    typer.echo(ui.key_value("task", getattr(task, "id", "-")))
    typer.echo(ui.key_value("status", status_value))
    for item in verification or ():
        command = item.get("command", "")
        if item.get("withheld"):
            ui.warning(f"whole-project verification withheld: {command}")
        elif item.get("passed"):
            ui.success(f"whole-project verification passed: {command}")
        else:
            detail = f" ({item['error']})" if item.get("error") else ""
            ui.warning(f"whole-project verification failed: {command}{detail}")
    typer.echo(ui.muted("-" * 62))


def run(
    instruction: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional seed instruction for the first cycle. Without it, "
                "Sprout derives work from a fresh project scan."
            )
        ),
    ] = None,
    path: Annotated[
        Path,
        typer.Option(
            "--path",
            "-C",
            help="Project root to operate on. Defaults to the current directory.",
        ),
    ] = Path("."),
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to sprout.toml."),
    ] = None,
    model_plan: Annotated[
        bool,
        typer.Option(
            "--model-plan",
            help="Let the configured model refine the strategy plan before coding.",
        ),
    ] = False,
) -> None:
    """Continuously scan the project through the full engineering loop.

    Each cycle runs project scan, strategy, coding, validation, integration,
    whole-project verification, and confirmation. The loop never stops on its
    own: every completed change is integrated, then followed by a fresh scan
    that proposes the next improvement. Interrupt with Ctrl+C to stop.
    """

    async def _run() -> None:
        from Sprout.config.loader import load_settings
        from Sprout.runtime.factory import create_runtime

        settings = load_settings(config)
        runtime = create_runtime(settings)
        await runtime.start()
        try:
            workspace = await runtime.open_workspace(path.resolve())
            ui.banner("Sprout Autonomous Run", subtitle=str(workspace.id))
            typer.echo(ui.key_value("project", workspace.root))
            typer.echo(ui.key_value("pipeline", _PIPELINE))
            typer.echo("")
            current = instruction.strip() if instruction else ""
            cycle = 0
            while True:
                cycle += 1
                if not current:
                    current = (
                        await _derive_next_instruction(runtime, workspace, "")
                        or _FALLBACK_INSTRUCTION
                    )
                task = await runtime.create_task_planned(
                    workspace.id,
                    current,
                    actor=Principal(user_id="cli-user", source="cli"),
                    source="cli",
                    use_model_planner=model_plan,
                )
                await runtime.execute(task)
                task = await runtime.get_task(task.id) or task
                if task.status is TaskStatus.WAITING_APPROVAL:
                    task, quit_loop = await _resolve_approvals(runtime, task)
                    if quit_loop:
                        break
                verification: list[dict[str, Any]] | None = None
                if task.status is TaskStatus.COMPLETED:
                    verification = await _whole_project_verify(runtime, task)
                _print_cycle(cycle, task, current, verification)
                current = (
                    await _derive_next_instruction(runtime, workspace, current)
                    or _FALLBACK_INSTRUCTION
                )
        finally:
            await runtime.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("")
        typer.echo(ui.muted("autonomous run stopped"))

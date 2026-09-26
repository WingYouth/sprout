"""``sprout run``: autonomous, looping project automation for one workspace."""

from __future__ import annotations

import asyncio
import inspect
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
    ask_approval,
)
from Sprout.cli.diff import render_diff
from Sprout.cli.i18n import L as _L
from Sprout.execution.models import ChangeProposalStatus
from Sprout.gateway.identity import Principal
from Sprout.llm.messages import LLMMessage
from Sprout.task.models import TaskStatus
from Sprout.workspace.models import WorkspaceManifest

_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("扫描", "scan"),
    ("策略", "strategy"),
    ("编码", "coding"),
    ("验证", "validation"),
    ("融合", "integrate"),
    ("测试", "verify"),
    ("确认", "confirm"),
)
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
        return _L("无项目扫描信息", "no manifest available")
    parts: list[str] = []
    if manifest.detected_languages:
        parts.append(_L("语言", "languages") + "=" + ",".join(manifest.detected_languages))
    if manifest.framework_hints:
        parts.append(_L("框架", "frameworks") + "=" + ",".join(manifest.framework_hints))
    if manifest.entry_points:
        parts.append(_L("入口", "entry_points") + "=" + ",".join(manifest.entry_points))
    if manifest.test_commands:
        parts.append(_L("测试", "test") + "=" + "; ".join(manifest.test_commands))
    if manifest.build_commands:
        parts.append(_L("构建", "build") + "=" + "; ".join(manifest.build_commands))
    return "; ".join(parts) or _L("没有可显示的扫描细节", "no manifest details")


def _pipeline_text() -> str:
    return " -> ".join(_L(zh, en) for zh, en in _PIPELINE_STEPS)


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


async def _ask_approval(
    message: str, *, allow_similar: bool = False, allow_quit: bool = False
) -> str | None:
    """Ask the operator to decide one pending approval.

    Returns the shared CLI approval decision. A non-interactive terminal
    returns ``None`` so the loop leaves the decision parked instead of guessing.
    """
    return await ask_approval(
        message, allow_similar=allow_similar, allow_quit=allow_quit
    )


async def _approval_choice(message: str, **kwargs: Any) -> str | None:
    """Call the approval hook, accepting sync monkeypatches in tests."""
    choice = _ask_approval(message, **kwargs)
    if inspect.isawaitable(choice):
        return await choice
    return choice


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
        detail.append(f"{_L('文件', 'files')}: {names}")
    if verification_status:
        detail.append(f"{_L('验证', 'verification')}: {verification_status}")
    prefix = (
        f"{_L('应用变更提案', 'Apply change proposal')} "
        f"{str(getattr(proposal, 'id', ''))[:8]}"
    )
    if summary:
        prefix += f": {summary[:80]}"
    return prefix + ("  " + " | ".join(detail) if detail else "")


def _run_authorization_prompt(
    *,
    project: Path,
    manifest: WorkspaceManifest | None,
    pipeline: str | None = None,
) -> str:
    commands: list[str] = []
    if manifest is not None:
        commands.extend(manifest.test_commands)
        commands.extend(manifest.build_commands)
    command_text = (
        "; ".join(dict.fromkeys(commands))
        or _L("项目扫描推导出的测试/构建命令", "project-derived test/build commands")
    )
    pipeline = pipeline or _pipeline_text()
    return (
        f"{_L('授权这次 Sprout 运行？', 'Authorize this Sprout run?')}\n"
        f"{_L('项目', 'project')}: {project}\n"
        f"{_L('流程', 'pipeline')}: {pipeline}\n"
        f"{_L('命令', 'commands')}: {command_text}\n"
        + _L(
            "这一次授权将覆盖本次运行中的项目扫描、策略制定、沙箱编码、冒烟检查、融合、全项目测试和最终确认。",
            "This single approval covers project scanning, strategy, coding in a sandbox, "
            "smoke checks, integration, whole-project tests, and final confirmation for "
            "this run.",
        )
    )


async def _resolve_approvals(
    runtime: Any,
    task: Any,
    *,
    auto_approve: bool = False,
) -> tuple[Any, bool]:
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
        if auto_approve:
            choice = APPROVE_SIMILAR if getattr(record, "approval_class", "") else APPROVE
            ui.success(
                f"{_L('已自动批准', 'auto-approved')} "
                f"{getattr(record, 'tool', 'action')}: {summary}"
            )
        else:
            choice = await _approval_choice(
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
                record.id,
                choice != REJECT,
                decided_by="sprout-run" if auto_approve else "cli",
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
        if auto_approve:
            choice = APPROVE
            ui.success(
                f"{_L('已自动批准变更提案', 'auto-approved change proposal')} "
                f"{str(proposal.id)[:8]}"
            )
        else:
            for diff in getattr(proposal, "diffs", ()) or ():
                render_diff(diff.path, diff.diff_text)
            choice = await _approval_choice(_proposal_prompt(proposal), allow_quit=True)
        if choice == QUIT:
            return task, True
        if choice == APPROVE:
            await runtime.approve_change_proposal(
                proposal.id,
                decided_by="sprout-run" if auto_approve else "cli",
            )
        elif choice == REJECT:
            await runtime.reject_change_proposal(proposal.id)

    task = await runtime.get_task(task.id) or task
    return task, False


async def _whole_project_verify(
    runtime: Any,
    task: Any,
    *,
    auto_approve: bool = False,
) -> list[dict[str, Any]] | None:
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
            if auto_approve and getattr(outcome, "needs_approval", False):
                approval_id = getattr(outcome, "approval_id", None)
                if approval_id:
                    await runtime.decide_approval(
                        approval_id,
                        True,
                        decided_by="sprout-run",
                        resume_session=False,
                    )
                    label = _L(
                        "已自动批准全项目验证",
                        "auto-approved whole-project verification",
                    )
                    ui.success(f"{label}: {command}")
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
    typer.echo(ui.text(f"{_L('循环', 'cycle')} {cycle}", bold=True))
    typer.echo(ui.key_value(_L("指令", "instruction"), instruction))
    typer.echo(ui.key_value(_L("任务", "task"), getattr(task, "id", "-")))
    typer.echo(ui.key_value(_L("状态", "status"), status_value))
    for item in verification or ():
        command = item.get("command", "")
        if item.get("withheld"):
            ui.warning(
                f"{_L('全项目验证待授权', 'whole-project verification withheld')}: "
                f"{command}"
            )
        elif item.get("passed"):
            ui.success(f"{_L('全项目验证通过', 'whole-project verification passed')}: {command}")
        else:
            detail = f" ({item['error']})" if item.get("error") else ""
            ui.warning(
                f"{_L('全项目验证失败', 'whole-project verification failed')}: "
                f"{command}{detail}"
            )
    typer.echo(ui.muted("-" * 62))


def run(
    instruction: Annotated[
        str | None,
        typer.Argument(
            help=_L(
                "首轮可选种子指令。不填写时，Sprout 会根据项目扫描自动推导工作。",
                "Optional seed instruction for the first cycle. Without it, "
                "Sprout derives work from a fresh project scan.",
            )
        ),
    ] = None,
    path: Annotated[
        Path,
        typer.Option(
            "--workspace",
            "--path",
            "-C",
            help=_L(
                "要操作的项目根目录；npm/后台启动时请显式传入。",
                "Project root to operate on; pass it explicitly from npm/background launchers.",
            ),
        ),
    ] = Path("."),
    config: Annotated[
        str | None,
        typer.Option("--config", help=_L("sprout.toml 路径。", "Path to sprout.toml.")),
    ] = None,
    model_plan: Annotated[
        bool,
        typer.Option(
            "--model-plan",
            help=_L(
                "编码前让配置的大模型细化策略计划。",
                "Let the configured model refine the strategy plan before coding.",
            ),
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help=_L(
                "不弹交互提示，直接授予本次运行权限。仅在你信任该项目和命令上下文时使用。",
                "Approve the whole run up front without an interactive prompt. "
                "Use only when you trust this project and command context.",
            ),
        ),
    ] = False,
    per_step_approvals: Annotated[
        bool,
        typer.Option(
            "--per-step-approvals",
            help=_L(
                "保留旧行为：每个阶段需要权限时都再次询问。",
                "Keep the legacy behavior: ask again whenever a phase needs approval.",
            ),
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
            manifest = await runtime.scan_workspace(workspace.id)
            ui.banner(_L("Sprout 自动运行", "Sprout Autonomous Run"), subtitle=str(workspace.id))
            typer.echo(ui.key_value(_L("项目", "project"), workspace.root))
            typer.echo(ui.key_value(_L("流程", "pipeline"), _pipeline_text()))
            typer.echo(ui.key_value(_L("检测结果", "detected"), _manifest_brief(manifest)))
            typer.echo("")
            auto_approve = not per_step_approvals
            if auto_approve and yes:
                ui.success(
                    _L(
                        "已通过 --yes 授予本次运行权限",
                        "run-level approval granted by --yes",
                    )
                )
            elif auto_approve:
                choice = await _approval_choice(
                    _run_authorization_prompt(
                        project=workspace.root,
                        manifest=manifest,
                    ),
                    allow_quit=True,
                )
                if choice == QUIT:
                    return
                if choice != APPROVE:
                    ui.warning(
                        _L(
                            "未授予本次运行权限，自动运行已取消",
                            "run-level approval was not granted; autonomous run cancelled",
                        )
                    )
                    raise typer.Exit(code=1)
                ui.success(_L("已授予本次运行权限", "run-level approval granted"))
            else:
                ui.warning(
                    _L(
                        "已启用逐步审批；后续阶段可能继续询问权限",
                        "per-step approvals enabled; phases may ask again",
                    )
                )
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
                    task, quit_loop = await _resolve_approvals(
                        runtime,
                        task,
                        auto_approve=auto_approve,
                    )
                    if quit_loop:
                        break
                verification: list[dict[str, Any]] | None = None
                if task.status is TaskStatus.COMPLETED:
                    verification = await _whole_project_verify(
                        runtime,
                        task,
                        auto_approve=auto_approve,
                    )
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
        typer.echo(ui.muted(_L("自动运行已停止", "autonomous run stopped")))

"""``sprout chat``: one-shot or interactive conversation through the runtime."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import shutil
import sys
import webbrowser
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.shortcuts.prompt import CompleteStyle
from prompt_toolkit.styles import Style
from pygments.style import Style as PygmentsStyle
from pygments.token import Token
from rich.cells import cell_len
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text
from rich.theme import Theme

from Sprout.cli import ui
from Sprout.cli.approval_prompt import (
    APPROVE,
    APPROVE_SIMILAR,
    APPROVE_WITH_FAILURES,
    REJECT,
    approval_select_style,
    ask_approval,
)
from Sprout.cli.diff import render_diff
from Sprout.cli.i18n import L as _L
from Sprout.cli.i18n import current_language as _current_cli_language
from Sprout.cli.i18n import language_command as _language_command
from Sprout.cli.i18n import language_name as _language_name
from Sprout.cli.i18n import set_language as _set_cli_language
from Sprout.cli.i18n import supported_languages as _supported_languages
from Sprout.gateway.identity import Principal
from Sprout.llm.messages import Usage
from Sprout.message.models import Message
from Sprout.runtime.changes import blocking_test_failures
from Sprout.security.redact import Redactor

_CHAT_HISTORY = InMemoryHistory()
_PURPLE = "#a855f7"
_GREEN = "#34d399"
_CODE_BLOCK_BG = "#332126"
_WEB_PROCESS: asyncio.subprocess.Process | None = None


class _CliCodeTheme(PygmentsStyle):
    default_style = _GREEN
    background_color = _CODE_BLOCK_BG
    styles = {Token: _GREEN}


_CLI_CODE_THEME = _CliCodeTheme
_CLI_MARKDOWN_THEME = Theme(
    {
        "markdown.code": _GREEN,
        "markdown.code_block": f"{_GREEN} on {_CODE_BLOCK_BG} not bold",
        "markdown.h1": f"bold {_PURPLE}",
        "markdown.h2": f"bold {_PURPLE}",
        "markdown.h3": f"bold {_PURPLE}",
        "markdown.h4": f"bold {_PURPLE}",
        "markdown.h5": f"bold {_PURPLE}",
        "markdown.h6": f"bold {_PURPLE}",
        "markdown.strong": f"bold {_PURPLE}",
        "markdown.table.header": f"{_GREEN} not bold",
        "markdown.item.number": "white",
    }
)
_ASCII_LOGO = r"""
   ███████╗██████╗ ██████╗  ██████╗ ██╗   ██╗████████╗
   ██╔════╝██╔══██╗██╔══██╗██╔═══██╗██║   ██║╚══██╔══╝
   ███████╗██████╔╝██████╔╝██║   ██║██║   ██║   ██║
   ╚════██║██╔═══╝ ██╔══██╗██║   ██║██║   ██║   ██║
   ███████║██║     ██║  ██║╚██████╔╝╚██████╔╝   ██║
   ╚══════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝  ╚═════╝    ╚═╝
"""


def _centered_logo() -> str:
    lines = [line.strip() for line in _ASCII_LOGO.strip().splitlines()]
    width = max(len(line) for line in lines)
    left_pad = max((62 - width) // 2, 0)
    return "\n".join(" " * left_pad + line for line in lines)


class _CLIStreamPreview:
    """Remove emphasis delimiters while keeping stream rendering cheap."""

    def __init__(self) -> None:
        self._pending = ""
        self._in_fence = False
        self._emphasis = False

    def process(self, text: str, *, final: bool = False) -> Text:
        data = self._pending + text
        self._pending = ""
        if not final and data.endswith(("``", "`", "*", "_")):
            pending_len = 2 if data.endswith("``") else 1
            data, self._pending = data[:-pending_len], data[-pending_len:]

        output = Text()
        index = 0
        while index < len(data):
            if data.startswith("```", index):
                self._in_fence = not self._in_fence
                output.append("```")
                index += 3
                continue
            if not self._in_fence and (
                data.startswith("**", index) or data.startswith("__", index)
            ):
                self._emphasis = not self._emphasis
                index += 2
                continue
            output.append(
                data[index],
                style="bold" if self._emphasis else None,
            )
            index += 1
        return output


def _cli_model_text(text: str) -> str:
    """Keep the model's Markdown source intact for the terminal renderer."""
    return text


def _render_cli_markdown(text: str) -> None:
    """Render one complete model response as terminal Markdown."""
    Console(theme=_CLI_MARKDOWN_THEME).print(
        Markdown(_cli_model_text(text), code_theme=_CLI_CODE_THEME), end=""
    )


def _render_cli_markdown_text(text: str) -> str:
    """Render Markdown to plain text for non-terminal tests and callers."""
    output = StringIO()
    Console(
        file=output,
        force_terminal=False,
        color_system=None,
        theme=_CLI_MARKDOWN_THEME,
    ).print(
        Markdown(_cli_model_text(text), code_theme=_CLI_CODE_THEME), end=""
    )
    return output.getvalue()


def chat(
    message: Annotated[
        str | None,
        typer.Argument(
            help="Message to send now. Omit this argument to start an interactive chat."
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            "-s",
            help="Continue an existing session by id. Useful after a previous chat printed one.",
        ),
    ] = None,
    user: Annotated[
        str,
        typer.Option("--user", help="Identity recorded on messages and turns."),
    ] = "cli-user",
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to sprout.toml."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Override the configured model provider (echo, aiyallm, or openai_compatible).",
        ),
    ] = None,
) -> None:
    """Send one message through the runtime, or start interactive chat.

    With no MESSAGE, the command starts a local REPL. An empty line or Ctrl+C
    exits the interactive loop. Use --session to continue a previous session.
    """
    from Sprout.cli.commands.model import model_configuration_issues
    from Sprout.config.loader import load_settings
    from Sprout.runtime.factory import create_runtime

    settings = load_settings(config)
    if model:
        settings.model.provider = model
    issues = model_configuration_issues(settings)
    if issues:
        typer.echo(ui.warning("尚未完成模型配置，聊天不会启动。"))
        for issue in issues:
            typer.echo(ui.muted(f"- {issue}"))
        typer.echo(
            ui.text(
                "请先配置：uv run sprout model set "
                "--provider aiyallm --model <model> --base-url <url>"
            )
        )
        raise typer.Exit(code=2)
    runtime = create_runtime(settings)

    asyncio.run(_chat(runtime, settings, message=message, session=session, user=user))


async def _chat(runtime, settings, *, message: str | None, session: str | None, user: str) -> None:
    from Sprout.gateway.transport_gateways import CLIGateway
    from Sprout.runtime.lifecycle import managed

    subtitle = _L(
        "自我进化的软件项目基因引擎",
        "A self-evolving gene for software projects",
    )
    rule = "=" * 62
    typer.secho(rule, fg=ui.PURPLE)
    typer.secho("SEAM Sprout".center(62), fg=ui.PURPLE, bold=True)
    typer.echo("")
    typer.echo("")
    typer.echo(ui.text(_centered_logo(), bold=True))
    typer.echo("")
    typer.echo(ui.muted(subtitle.rjust(32)))
    typer.secho(rule, fg=ui.PURPLE)
    typer.echo(
        ui.muted(
            _L(
                "项目分析 · 代码生成 · 隔离执行 · 验证 · 集成",
                "Project analysis · code generation · isolated execution · "
                "verification · integration",
            )
        )
    )
    typer.echo(ui.muted(_L("输入 `/` 探索命令", "Use `/` to explore commands.")))
    _print_session_separator()

    mcp_manager = None
    if settings.mcp.clients:
        from Sprout.mcp.client import attach_mcp_clients

        mcp_manager = await attach_mcp_clients(runtime, settings)
    if settings.evolution.enabled:
        from Sprout.evolution import attach_evolution

        attach_evolution(runtime, settings)

    try:
        async with managed(runtime):
            workspace_id = await _confirm_cli_workspace(runtime)
            gateway = CLIGateway(runtime)
            if message is not None:
                file_location = await _file_location_answer(
                    message, runtime=runtime, workspace_id=workspace_id
                )
                if file_location is not None:
                    typer.echo(file_location)
                    _print_session_separator()
                    return
                directory = _current_directory_answer(message)
                if directory is not None:
                    typer.echo(directory)
                    _print_session_separator()
                    return
                if _handle_natural_language_request(message):
                    return
                reply = await gateway.handle_message(
                    Message(
                        message,
                        channel="cli",
                        user_id=user,
                        session_id=session,
                        metadata={
                            "cli_language": _current_cli_language(),
                            "foreground_task": True,
                            **({"workspace_id": workspace_id} if workspace_id else {}),
                        },
                    )
                )
                _render_cli_markdown(reply.content)
                _print_reply_meta(reply.metadata)
                # One-shot mode (``sprout chat "..."``) can still answer: the
                # prompt runs here rather than being silently dropped, which
                # would leave a held task nobody knows about.
                handled = await _handle_cli_workspace_consent(
                    runtime, reply.session_id or session, dict(reply.metadata), user
                )
                if not handled:
                    if dict(reply.metadata).get("foreground_task"):
                        await _continue_foreground_task(
                            runtime, dict(reply.metadata), user
                        )
                        handled = True
                    else:
                        await _handle_cli_approval_prompt(
                            runtime, reply.session_id or session, dict(reply.metadata), user
                        )
                await _report_parked_tasks(runtime, reply.session_id or session)
                _print_session_separator()
                return
            await _repl(
                gateway,
                session=session,
                user=user,
                model=settings.model,
                runtime=runtime,
                web=settings.web,
                workspace_id=workspace_id,
            )
    finally:
        if mcp_manager is not None:
            await mcp_manager.stop()


def _apply_language_request(language: str) -> None:
    _set_cli_language(language)
    typer.echo(
        ui.muted(
            f"{_L('已切换到：', 'Switched to:')} "
            f"{_language_name(_current_cli_language())}"
        )
    )


def _handle_natural_language_request(content: str) -> bool:
    """Recognise an explicit language intent and execute ``/language <lang>``."""
    command = _language_command(content)
    if command is None:
        return False
    _, requested = command
    _apply_language_request(requested)
    return True


def _current_directory_answer(content: str) -> str | None:
    """Answer a narrow environment question from the CLI process itself."""
    normalized = content.strip().rstrip("?？。.!！").casefold()
    questions = {
        "当前在哪个目录",
        "我当前在哪个目录",
        "我现在在哪个目录",
        "现在在哪个目录",
        "当前工作目录是什么",
        "what directory am i in",
        "what is the current directory",
        "what is my current directory",
        "where am i",
    }
    if normalized not in questions:
        return None
    return _L("当前 CLI 进程目录：", "Current CLI process directory: ") + str(
        Path.cwd().resolve()
    )


async def _file_location_answer(
    content: str, *, runtime: Any, workspace_id: str = ""
) -> str | None:
    """Resolve a file location by exact path, without recursively scanning."""
    if not any(
        marker in content.casefold()
        for marker in ("写到哪里", "写到哪", "在哪里", "在哪", "位置", "where")
    ):
        return None
    matches = re.findall(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9]+", content)
    if not matches:
        return None
    requested = Path(matches[0]).expanduser()
    workspace = await runtime.get_workspace(workspace_id) if workspace_id else None
    root = Path(workspace.root).resolve() if workspace is not None else Path.cwd().resolve()
    candidate = (root / requested).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return _L("文件路径超出当前工作区。", "The file path is outside the current workspace.")
    if candidate.is_file():
        return _L("文件位置：", "File location: ") + str(candidate)
    return _L(
        f"工作区根目录中没有 {requested.as_posix()}：{root}",
        f"{requested.as_posix()} does not exist at the workspace root: {root}",
    )


async def _execute_language_command(requested: str | None = None) -> None:
    selected = requested or await _prompt_language_subcommand()
    if selected:
        _apply_language_request(selected)


async def _repl(
    gateway,
    *,
    session: str | None,
    user: str,
    model,
    runtime,
    web,
    workspace_id: str = "",
) -> None:
    typer.echo(ui.text(_L("交互式对话", "Interactive chat"), bold=True))
    typer.echo(
        ui.muted(
            _L(
                "每次输入一行消息，空行或 Ctrl+C 退出；首次回复后会显示会话 ID。",
                "Type one message per line. Empty line or Ctrl+C exits. "
                "The session id is printed after the first reply.",
            )
        )
    )
    if session:
        typer.echo(ui.key_value("session", session))
    typer.echo(
        ui.muted(
            _L(
                f"模型：{model.provider} ({model.model})",
                f"model: {model.provider} ({model.model})",
            )
        )
    )
    typer.echo("")
    while True:
        try:
            content = await _readline_with_slash_hint()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\n" + ui.muted(_L("对话已结束", "Chat ended.")))
            break
        if not content:
            continue
        file_location = await _file_location_answer(
            content, runtime=runtime, workspace_id=workspace_id
        )
        if file_location is not None:
            typer.echo(ui.text(file_location))
            continue
        directory = _current_directory_answer(content)
        if directory is not None:
            typer.echo(ui.text(directory))
            continue
        if _handle_natural_language_request(content):
            continue
        if content.startswith("/"):
            if content in {"/", "/help"}:
                if content == "/help":
                    _show_slash_directory()
                continue
            if content == "/session":
                await _stream_sprout_command(["session", "--help"])
                continue
            if content == "/info":
                from Sprout.cli.commands.info import info

                info()
                continue
            if content in {
                "/mcp",
                "/memory",
                "/project",
                "/remote",
                "/evolution",
                "/approvals",
                "/audit",
                "/storage",
                "/serve",
                "/orchestrator",
            }:
                await _stream_sprout_command([content[1:], "--help"])
                continue
            if content in {"/skill", "/skills"} or content.startswith(("/skill ", "/skills ")):
                await _handle_skill_command(content)
                continue
            if content == "/language":
                await _execute_language_command()
                continue
            if content.startswith("/language "):
                requested = content.split(" ", 1)[1].strip()
                await _execute_language_command(requested)
                continue
            if content == "/clear":
                typer.echo("\033[2J\033[H", nl=False)
                continue
            if content in {"/q", "/quit", "/exit"}:
                typer.echo(ui.muted(_L("对话已结束", "Chat ended.")))
                break
            if content == "/stop":
                typer.echo(
                    ui.muted(
                        _L(
                            "当前会话已停止，开始新会话",
                            "Session stopped. Starting a new session.",
                        )
                    )
                )
                continue
            if content == "/gateway":
                while True:
                    selected = await _prompt_gateway_subcommand()
                    if not selected:
                        break
                    if await _setup_gateway_in_chat(selected):
                        break
                continue
            if content == "/db":
                while True:
                    action = await _prompt_db_action()
                    if not action:
                        break
                    await _execute_db_action(action)
                continue
            if content == "/model":
                await _prompt_model_action()
                continue
            if content == "/task" or content.startswith("/task "):
                instruction = content.removeprefix("/task").strip()
                if not instruction:
                    typer.echo(
                        ui.warning(
                            _L("用法：/task <指令>", "Usage: /task <instruction>")
                        )
                    )
                    continue
                if not workspace_id:
                    workspace_id = (await runtime.open_workspace(Path.cwd())).id
                task = await runtime.create_task_planned(
                    workspace_id,
                    instruction,
                    actor=Principal(user_id=user, source="cli"),
                    source="cli",
                    language=_current_cli_language(),
                )
                if session:
                    task = replace(
                        task,
                        metadata={**dict(task.metadata), "session_id": session},
                    )
                    await runtime.storage.metadata.save_task(task)
                await runtime.execute(task)
                await _continue_foreground_task(runtime, {"task_id": task.id}, user)
                continue
            if content == "/status" or content.startswith("/status "):
                task_id = content.removeprefix("/status").strip()
                if not task_id:
                    typer.echo(
                        ui.warning(
                            _L("用法：/status <task_id>", "Usage: /status <task_id>")
                        )
                    )
                    continue
                task = await runtime.get_task(task_id)
                if task is None:
                    candidates = [
                        item
                        for item in await runtime.list_tasks()
                        if str(item.id).startswith(task_id)
                    ]
                    if len(candidates) == 1:
                        task = candidates[0]
                if task is None:
                    typer.echo(
                        ui.warning(
                            _L(f"找不到任务：{task_id}", f"Task not found: {task_id}")
                        )
                    )
                    continue
                typer.echo(ui.key_value("task", task.id))
                typer.echo(ui.key_value("status", task.status.value))
                typer.echo(ui.key_value("instruction", task.instruction[:80]))
                await _approve_task_gates(runtime, task, user)
                continue
            if content == "/web":
                url = f"http://{web.host}:{web.port}"
                typer.echo(
                    ui.muted(
                        _L(
                            f"正在启动并打开 {url}",
                            f"Starting and opening {url}",
                        )
                    )
                )
                ready, started = await _ensure_web_server(web.host, web.port)
                if started:
                    typer.echo(
                        ui.muted(
                            _L(
                                "Web 控制台已在后台启动",
                                "Web console started in the background",
                            )
                        )
                    )
                if not ready:
                    typer.echo(
                        ui.warning(
                            _L(
                                "Web 控制台启动超时，仍尝试打开浏览器",
                                "Web console startup timed out; opening browser anyway",
                            )
                        )
                    )
                webbrowser.open(url)
                continue
            if content in {"/gateway feishu", "/gateway wechat-ilink"}:
                await _setup_gateway_in_chat(content.split(" ", 1)[1])
                continue
            hints = _hints()
            if content in hints:
                typer.echo(ui.muted(hints[content]))
                continue
            typer.echo(ui.warning(_L(f"未知命令：{content}", f"Unknown command: {content}")))
            _show_slash_directory()
            continue
        stream_message = Message(
            content=content,
            channel="cli",
            user_id=user,
            session_id=session,
            metadata={
                "cli_language": _current_cli_language(),
                "foreground_task": True,
                **({"workspace_id": workspace_id} if workspace_id else {}),
            },
        )
        response_chunks: list[str] = []
        reply_metadata: dict = {}
        response_error: str | None = None
        console = Console(theme=_CLI_MARKDOWN_THEME)
        if console.is_terminal:
            with Live(
                Spinner(
                    "dots",
                    text=Text(
                        _L("正在生成…", "Generating…"),
                        style="dim",
                    ),
                ),
                console=console,
                refresh_per_second=12,
                vertical_overflow="crop",
            ) as live:
                async for chunk in runtime.handle_stream(stream_message):
                    if chunk.error is not None:
                        response_error = chunk.error
                        break
                    if chunk.content:
                        response_chunks.append(chunk.content)
                        live.update(
                            Markdown(
                                "".join(response_chunks),
                                code_theme=_CLI_CODE_THEME,
                            )
                        )
                    if chunk.outbound is not None:
                        session = chunk.outbound.session_id
                        reply_metadata = dict(chunk.outbound.metadata)
        else:
            typer.echo(ui.muted(_L("  正在生成…", "  Generating…")))
            async for chunk in runtime.handle_stream(stream_message):
                if chunk.error is not None:
                    response_error = chunk.error
                    break
                if chunk.content:
                    response_chunks.append(chunk.content)
                if chunk.outbound is not None:
                    session = chunk.outbound.session_id
                    reply_metadata = dict(chunk.outbound.metadata)
        if response_error is not None:
            typer.secho(response_error, fg=typer.colors.RED)
        elif response_chunks:
            if not console.is_terminal:
                _render_cli_markdown("".join(response_chunks))
            console.print()
        elif not (
            reply_metadata.get("foreground_task") and reply_metadata.get("task_id")
        ):
            console.print(
                Markdown(
                    _L(
                        "模型暂时没有返回内容，请重试。",
                        "The model returned no content. Please try again.",
                    ),
                    code_theme=_CLI_CODE_THEME,
                )
            )
        _print_reply_meta(reply_metadata)
        handled = False
        if await _handle_cli_workspace_consent(runtime, session, reply_metadata, user):
            handled = True
        elif reply_metadata.get("foreground_task"):
            await _continue_foreground_task(runtime, reply_metadata, user)
            handled = True
        elif await _handle_cli_approval_prompt(runtime, session, reply_metadata, user):
            handled = True
        # After the handlers, so a task they just queued is included. Those two
        # print their own separator, hence the early continue.
        await _report_parked_tasks(runtime, session)
        task_id = str(reply_metadata.get("task_id") or "")
        if task_id and not reply_metadata.get("foreground_task"):
            runtime.schedule_background(_watch_background_task(runtime, task_id))
        if handled:
            continue
        if not session:
            typer.echo("")
        _print_session_separator()


async def _approve_task_gates(runtime: Any, task: Any, user: str) -> None:
    """Handle each distinct gate in one /status interaction."""
    parked = {"waiting_approval", "waiting_resource", "ready_to_apply"}
    while True:
        current = await runtime.get_task(task.id) or task
        if current.status.value not in parked:
            typer.echo(ui.key_value("status", current.status.value))
            return

        kind, handle = await runtime.task_progress(current)
        if kind == "approval" and handle:
            record = await runtime.approvals.store.get_approval(handle)
            if record is None:
                typer.echo(
                    ui.warning(_L("审批记录已不存在。", "Approval record no longer exists."))
                )
                return
            typer.echo(ui.key_value("next", f"sprout approvals approve {handle}"))
            _print_approval_record(record)
            prompt = (
                _L("允许执行这条沙箱验证命令？", "Allow this sandbox verification command?")
                if record.tool == "process_run"
                else _L("批准这个权限操作？", "Approve this permission request?")
            )
            choice = await _prompt_task_gate_choice(
                prompt, allow_similar=bool(record.approval_class)
            )
            if choice == REJECT:
                await runtime.decide_approval(
                    record.id,
                    False,
                    decided_by=user,
                    channel="cli",
                )
                return
            if choice == APPROVE_SIMILAR:
                record.single_use = False
                await runtime.approvals.store.save_approval(record)
            elif choice != APPROVE:
                return
            await runtime.decide_approval(
                record.id,
                True,
                decided_by=user,
                channel="cli",
            )
            typer.echo(
                ui.success(
                    _L(
                        "验证权限已批准，正在检查下一步。",
                        "Verification approved; checking the next step.",
                    )
                )
            )
            continue

        if kind == "proposal" and handle:
            proposal = await runtime.find_change_proposal(handle)
            if proposal is None:
                typer.echo(
                    ui.warning(_L("变更提案已不存在。", "Change proposal no longer exists."))
                )
                return
            typer.echo(ui.key_value("next", f"sprout project approve {handle}"))
            typer.echo(ui.key_value("files", ", ".join(proposal.files_changed) or "-"))
            for diff in proposal.diffs:
                render_diff(diff.path, diff.diff_text)
            relevant_failures = blocking_test_failures(
                proposal.test_results, proposal.files_changed
            )
            has_failures = bool(relevant_failures)
            if has_failures:
                typer.echo(
                    ui.warning(
                        _L(
                            "相关验证未通过：{checks}。选择“是”将接受该结果并融入。",
                            "Relevant verification failed: {checks}. Selecting “Yes” accepts "
                            "that result and applies the change.",
                        ).format(
                            checks="、".join(relevant_failures)
                            if _current_cli_language() == "zh"
                            else ", ".join(relevant_failures)
                        )
                    )
                )
            prompt = (
                _L(
                    "验证失败：接受失败结果并融入这些文件？",
                    "Verification failed: accept the failures and apply these files?",
                )
                if has_failures
                else _L(
                    "检查完变更后，批准将这些文件合入当前项目？",
                    "After reviewing the diff, approve applying these files to the project?",
                )
            )
            choice = await _prompt_task_gate_choice(
                prompt, allow_failures=has_failures, yes_no=True
            )
            if choice == REJECT:
                await runtime.reject_change_proposal(
                    proposal.id, reason="Rejected in CLI approval menu"
                )
                continue
            if choice not in {APPROVE, APPROVE_WITH_FAILURES}:
                return
            await runtime.approve_change_proposal(
                proposal.id,
                decided_by=user,
                allow_failing_tests=choice == APPROVE_WITH_FAILURES,
            )
            typer.echo(
                ui.success(
                    _L("提案已批准，任务正在继续。", "Proposal approved; the task is continuing.")
                )
            )
            continue

        typer.echo(
            ui.key_value(
                "next",
                _L(
                    "当前没有可处理的审批项；任务可能仍在运行。",
                    "No actionable approval is pending; the task may still be running.",
                ),
            )
        )
        return


async def _prompt_task_gate_choice(
    prompt: str,
    *,
    allow_similar: bool = False,
    allow_failures: bool = False,
    yes_no: bool = False,
) -> str | None:
    return await ask_approval(
        prompt,
        allow_similar=allow_similar,
        allow_failures=allow_failures,
        yes_no=yes_no,
    )


def _show_slash_directory() -> None:
    """Print the available slash commands and what each one does."""
    for command, description in _slash_rows():
        typer.echo(f"  > {ui.text(command, bold=True)}  {ui.muted(description)}")
    typer.echo("")


async def _handle_cli_approval_prompt(
    runtime: Any,
    session_id: str | None,
    metadata: dict,
    user: str,
) -> bool:
    approval_ids = [
        str(approval_id)
        for approval_id in metadata.get("approval_ids", ())
        if approval_id
    ]
    if not session_id or not metadata.get("approval_required") or not approval_ids:
        return False

    decided = False
    approved_any = False
    for approval_id in approval_ids:
        record = await runtime.approvals.store.get_approval(approval_id)
        if record is None:
            typer.echo(ui.warning(_approval_text("missing", approval_id=approval_id)))
            continue
        _print_approval_record(record, metadata.get("pending_tool_calls"))
        choice = await _prompt_approval_decision(record)
        if choice == REJECT:
            await runtime.decide_approval(
                record.id,
                False,
                decided_by=user,
                reason=_approval_text("rejected_reason"),
                channel="cli",
            )
            typer.echo(ui.warning(_approval_text("rejected", approval_id=record.id[:8])))
            decided = True
            continue
        if choice == APPROVE:
            await runtime.decide_approval(
                record.id,
                True,
                decided_by=user,
                reason=_approval_text("approved_once_reason"),
                channel="cli",
                resume_session=False,
            )
            typer.echo(ui.success(_approval_text("approved_once", approval_id=record.id[:8])))
            approved_any = True
            decided = True
            continue
        if choice == APPROVE_SIMILAR:
            record.single_use = False
            await runtime.approvals.store.save_approval(record)
            await runtime.decide_approval(
                record.id,
                True,
                decided_by=user,
                reason=_approval_text("approved_similar_reason"),
                channel="cli",
                resume_session=False,
            )
            typer.echo(
                ui.success(_approval_text("approved_similar", approval_id=record.id[:8]))
            )
            approved_any = True
            decided = True

    if approved_any:
        typer.echo(ui.muted(_approval_text("resuming")))
        try:
            outbound = await runtime.resume_pending_task(
                session_id,
                user_id=user,
                response_language=_current_cli_language(),
            )
        except LookupError as exc:
            # A broker/event callback may have resumed the task while the CLI
            # was collecting the decision. Do not turn that harmless race into
            # a second fatal traceback.
            if "No pending approval found" not in str(exc):
                raise
            typer.echo(ui.muted(_approval_text("already_resumed")))
            return True
        _render_cli_markdown(outbound.content)
        _print_reply_meta(dict(outbound.metadata))
        if dict(outbound.metadata).get("approval_required"):
            await _handle_cli_approval_prompt(
                runtime,
                outbound.session_id,
                dict(outbound.metadata),
                user,
            )
            return True
        _print_session_separator()
    elif decided:
        _print_session_separator()
    return decided


async def _report_parked_tasks(runtime: Any, session_id: str | None) -> None:
    """Say which of this session's tasks are waiting on the operator.

    A task runs detached from the turn that created it, so the chat path cannot
    observe it stalling. The agent promises "I will tell you when it is done",
    and without this it cannot: the work parks on an approval and the person who
    asked hears nothing until they happen to run ``sprout approvals list``.
    That is not a hypothetical — a task wrote its file and sat there for a whole
    session while the user kept asking whether it was finished.

    Reported, never auto-decided: parking is the safety property, and a notice
    that resolved the thing it was reporting would defeat it.
    """
    if not session_id:
        return
    parked = await runtime.parked_tasks_for_session(session_id)
    if not parked:
        return
    typer.echo("")
    typer.echo(
        ui.warning(
            _L(
                f"有 {len(parked)} 个任务在等你决定：",
                f"{len(parked)} task(s) are waiting on you:",
            )
        )
    )
    for task in parked:
        kind, handle = await runtime.task_progress(task)
        short = task.id[:8]
        if kind == "proposal":
            typer.echo(
                ui.key_value(
                    f"  {short}",
                    _L(
                        f"变更提案待批 → sprout project approve {handle[:8]}",
                        f"change proposal pending → sprout project approve {handle[:8]}",
                    ),
                )
            )
        elif kind == "approval":
            typer.echo(
                ui.key_value(
                    f"  {short}",
                    _L(
                        f"授权待批 → sprout approvals approve {handle[:8]}",
                        f"approval pending → sprout approvals approve {handle[:8]}",
                    ),
                )
            )
        else:
            typer.echo(
                ui.key_value(
                    f"  {short}",
                    _L(
                        f"状态 {task.status.value}（暂无可直接处理的入口）",
                        f"status {task.status.value} (no direct action available)",
                    ),
                )
            )
    typer.echo("")
    typer.echo(
        ui.muted(
            _L("也可以用 /status <task_id> 看详情。", "See /status <task_id> for detail.")
        )
    )


async def _handle_cli_workspace_consent(
    runtime: Any,
    session_id: str | None,
    metadata: dict,
    user: str,
) -> bool:
    """Ask which workspace to run a coding task in, then resume it.

    The runtime holds the turn rather than creating a task, so saying no costs
    nothing: no workspace is registered and no task is queued until the answer
    is yes. Returning ``False`` lets the caller fall through to its normal
    end-of-turn rendering — the question was already printed as the reply.
    """
    if not session_id or not metadata.get("workspace_consent_required"):
        return False
    proposed = str(metadata.get("proposed_workspace_root") or "")
    if not proposed:
        return False
    typer.echo("")
    choice = await questionary.select(
        _workspace_consent_text("question", root=proposed),
        choices=[
            questionary.Choice(_workspace_consent_text("yes"), "yes"),
            questionary.Choice(_workspace_consent_text("no"), "no"),
        ],
        style=_select_style(),
    ).ask_async()
    if choice != "yes":
        typer.echo(ui.warning(_workspace_consent_text("declined")))
        return True
    try:
        outbound = await runtime.grant_workspace_consent(
            session_id, root=proposed, user_id=user
        )
    except LookupError as exc:
        typer.echo(ui.warning(_workspace_consent_text("expired", error=str(exc))))
        return True
    _render_cli_markdown(outbound.content)
    _print_reply_meta(dict(outbound.metadata))
    outbound_metadata = dict(outbound.metadata)
    task_id = str(outbound_metadata.get("task_id") or "")
    if task_id:
        if outbound_metadata.get("foreground_task"):
            await _continue_foreground_task(runtime, outbound_metadata, user)
        else:
            typer.echo(ui.muted(_workspace_consent_text("submitted", task_id=task_id)))
            runtime.schedule_background(_watch_background_task(runtime, task_id))
    return True


async def _confirm_cli_workspace(runtime: Any) -> str:
    """Confirm the CLI process' current directory once for its coding tasks."""
    if not sys.stdin.isatty():
        return ""
    root = Path.cwd().resolve()
    choice = await questionary.select(
        _L(
            f"确认本轮 CLI 会话的代码都在当前目录？\n{root}",
            f"Use the current directory for code tasks in this CLI session?\n{root}",
        ),
        choices=[
            questionary.Choice(_L("是，使用当前目录", "Yes, use this directory"), "current"),
            questionary.Choice(_L("否，稍后再选择", "No, choose later"), "later"),
        ],
        style=_select_style(),
    ).ask_async()
    if choice != "current":
        return ""
    workspace = await runtime.open_workspace(root)
    typer.echo(
        ui.muted(
            _L(
                f"本轮代码工作区：{root}",
                f"Code workspace for this CLI session: {root}",
            )
        )
    )
    return workspace.id


async def _continue_foreground_task(runtime: Any, metadata: dict, user: str) -> None:
    """Keep a CLI coding request in this turn, including all approval pauses."""
    task_id = str(metadata.get("task_id") or "")
    if not task_id:
        return
    task = await runtime.get_task(task_id)
    if task is None:
        typer.echo(ui.warning(_L("找不到当前任务。", "The current task could not be found.")))
        return
    parked = {"waiting_approval", "waiting_resource", "ready_to_apply"}
    if task.status.value in parked:
        await _approve_task_gates(runtime, task, user)
        task = await runtime.get_task(task_id) or task
    else:
        typer.echo(ui.key_value("status", task.status.value))

    nodes = await runtime.storage.metadata.list_execution_nodes(task_id)
    response = next(
        (
            str(output.get("content") or "")
            for node in reversed(nodes)
            if node.type.value == "agent"
            and isinstance((output := node.metadata.get("output")), dict)
            and output.get("content")
        ),
        "",
    )
    if response:
        _render_cli_markdown(response)
    _print_session_separator()


def _workspace_consent_text(key: str, **values: object) -> str:
    language = _current_cli_language()
    catalog = _WORKSPACE_CONSENT_TEXT.get(key, {})
    template = catalog.get(language) or catalog.get("en") or key
    return template.format(**values)


async def _watch_background_task(runtime: Any, task_id: str) -> None:
    """Report task gates and results without corrupting the active prompt."""
    last = None
    while getattr(runtime, "_started", True):
        await asyncio.sleep(1)
        if not getattr(runtime, "_started", True):
            return
        task = await runtime.get_task(task_id)
        if task is None:
            return
        status = task.status.value
        if status == last:
            continue
        last = status
        if status in {"waiting_approval", "waiting_resource", "ready_to_apply"}:
            kind, handle = await runtime.task_progress(task)
            if kind == "approval":
                action = f"sprout approvals approve {handle}"
                gate = _L("沙箱验证命令待审批", "sandbox verification command needs approval")
            elif kind == "proposal":
                action = f"sprout project approve {handle}"
                gate = _L("代码变更待合入审批", "code changes need apply approval")
            else:
                action = f"/status {task_id[:8]}"
                gate = _L("任务需要处理", "task needs attention")

            def show_gate(gate: str = gate, action: str = action) -> None:
                typer.echo(
                    ui.warning(
                        f"{task_id[:8]}：{gate}。运行 `{action}`，"
                        f"或输入 `/status {task_id[:8]}` 在当前会话继续。"
                    )
                )

            await run_in_terminal(show_gate)
        elif status in {"completed", "failed", "cancelled", "rolled_back"}:
            nodes = await runtime.storage.metadata.list_execution_nodes(task_id)
            response = next(
                (
                    str(output.get("content") or "")
                    for node in reversed(nodes)
                    if node.type.value == "agent"
                    and isinstance((output := node.metadata.get("output")), dict)
                    and output.get("content")
                ),
                "",
            )

            def show_result(status: str = status, response: str = response) -> None:
                label = _L(
                    f"任务 {task_id[:8]} 已结束（状态 {status}）。",
                    f"Task {task_id[:8]} finished ({status}).",
                )
                if status == "completed":
                    typer.echo(ui.success(label))
                else:
                    typer.echo(ui.warning(label))
                if response:
                    _render_cli_markdown(response)

            await run_in_terminal(show_result)
            return


_WORKSPACE_CONSENT_TEXT: dict[str, dict[str, str]] = {
    "question": {
        "zh": "以 {root} 作为本次任务的工作区？",
        "zh-Hant": "以 {root} 作為本次任務的工作區？",
        "en": "Use {root} as the workspace for this task?",
    },
    "yes": {
        "zh": "同意（本次任务）",
        "zh-Hant": "同意（本次任務）",
        "en": "Yes, for this task",
    },
    "no": {
        "zh": "不用了",
        "zh-Hant": "不用了",
        "en": "No",
    },
    "declined": {
        "zh": "已取消，没有创建任何工作区或任务。",
        "zh-Hant": "已取消，沒有建立任何工作區或任務。",
        "en": "Cancelled — no workspace was registered and no task was created.",
    },
    "expired": {
        "zh": "这个请求已经失效了：{error}",
        "zh-Hant": "這個請求已經失效了：{error}",
        "en": "This request is no longer pending: {error}",
    },
    "submitted": {
        "zh": "任务后台执行中。输入 /status {task_id} 查看进度；需要你审批时会在这里提示。",
        "zh-Hant": "任務背景執行中。輸入 /status {task_id} 查看進度；需要你審批時會在這裡提示。",
        "en": "The task is running in the background. Type /status {task_id} for progress; "
        "you will be prompted here if approval is needed.",
    },
}


def _format_tool_arguments(tool: str, arguments: dict[str, Any]) -> str:
    """Render one tool call as the action it performs, with secrets masked."""
    scrub = Redactor().scrub
    if tool == "cli_tool_run" and isinstance(arguments.get("args"), list):
        parts = [str(arguments.get("command") or "").strip()]
        parts.extend(str(item) for item in arguments["args"])
        rendered = " ".join(part for part in parts if part)
        extras = {
            key: value
            for key, value in arguments.items()
            if key not in {"command", "args"}
        }
        if extras:
            rendered += " " + json.dumps(extras, ensure_ascii=False, sort_keys=True)
        return scrub(rendered)
    return scrub(
        f"{tool} {json.dumps(dict(arguments), ensure_ascii=False, sort_keys=True, default=str)}"
    )


def _approval_action_lines(record: Any, pending: object) -> list[str]:
    """The concrete action(s) a grant would authorise, ready for a terminal."""
    matching = [
        item
        for item in (pending or ())
        if isinstance(item, dict) and item.get("name") == getattr(record, "tool", "")
    ]
    if matching:
        return [
            _format_tool_arguments(
                getattr(record, "tool", ""),
                item.get("arguments") or {},
            )
            for item in matching
        ]
    summary = getattr(record, "action_summary", "") or ""
    return [summary] if summary else []


def _print_approval_record(record: Any, pending: object = ()) -> None:
    typer.echo("")
    typer.echo(ui.text(_approval_text("title"), bold=True))
    scope = "similar_scope" if getattr(record, "approval_class", "") else "exact_scope"
    rows = _approval_detail_rows(record)
    rows.extend(
        (_approval_text("action"), line)
        for line in _approval_action_lines(record, pending)
    )
    rows.append((
        _approval_text("scope"),
        _approval_text(scope, command=_approval_command(record)),
    ))
    rendered = [f"{label}  {value or '-'}" for label, value in rows]
    width = max((cell_len(line) for line in rendered), default=0)
    typer.echo("+" + "-" * (width + 2) + "+")
    for line in rendered:
        typer.echo(f"| {line}{' ' * (width - cell_len(line))} |")
    typer.echo("+" + "-" * (width + 2) + "+")


def _approval_command(record: Any) -> str:
    try:
        summary = json.loads(getattr(record, "action_summary", "") or "{}")
    except (TypeError, ValueError):
        summary = {}
    command = summary.get("command") if isinstance(summary, dict) else None
    return str(command or getattr(record, "tool", "this operation"))


def _approval_detail_rows(record: Any) -> list[tuple[str, str]]:
    return [
        (_approval_text("id"), str(record.id)),
        (_approval_text("tool"), str(record.tool)),
        (_approval_text("scope"), str(record.resource_scope or "-")),
        (_approval_text("task"), str(record.task_id or "-")),
        (_approval_text("source"), str(record.source or "-")),
        (_approval_text("requested_by"), str(record.requested_by or "-")),
        (_approval_text("expires"), record.expires_at.isoformat() if record.expires_at else "-"),
    ]


async def _prompt_approval_decision(record: Any) -> str | None:
    return await ask_approval(
        _approval_text("question", tool=record.tool),
        allow_similar=bool(getattr(record, "approval_class", "")),
    )


def _approval_text(key: str, **values: object) -> str:
    language = _current_cli_language()
    catalog = _APPROVAL_TEXT.get(key, {})
    template = catalog.get(language) or catalog.get("en") or key
    return template.format(**values)


_APPROVAL_TEXT: dict[str, dict[str, str]] = {
    "action": {
        "zh": "将执行",
        "zh-Hant": "將執行",
        "en": "Action",
        "ja": "実行内容",
        "ko": "실행 내용",
        "ru": "Действие",
        "es": "Acción",
        "pt": "Ação",
    },
    "title": {
        "zh": "需要你确认权限",
        "zh-Hant": "需要你確認權限",
        "en": "Permission approval required",
        "ja": "権限の確認が必要です",
        "ko": "권한 승인이 필요합니다",
        "ru": "Требуется подтверждение разрешения",
        "es": "Se requiere aprobación de permiso",
        "pt": "Aprovação de permissão necessária",
    },
    "question": {
        "zh": "是否允许执行这个操作：{tool}？",
        "zh-Hant": "是否允許執行這個操作：{tool}？",
        "en": "Allow this operation: {tool}?",
        "ja": "この操作を許可しますか: {tool}?",
        "ko": "이 작업을 허용할까요: {tool}?",
        "ru": "Разрешить эту операцию: {tool}?",
        "es": "¿Permitir esta operación: {tool}?",
        "pt": "Permitir esta operação: {tool}?",
    },
    "similar_scope": {
        "zh": "说明：{command} 同类授权仅适用于当前任务和会话，不是全局授权。",
        "zh-Hant": "說明：{command} 同類授權僅適用於目前任務和對話，不是全域授權。",
        "en": (
            "Note: {command} class approval covers this task and session; "
            "it is not a global grant."
        ),
        "ja": (
            "注: {command} の同種許可は現在のタスクとセッションに限定され、"
            "全体への許可ではありません。"
        ),
        "ko": (
            "참고: {command} 유형 허용은 현재 작업과 세션에만 적용되며 "
            "전역 권한이 아닙니다."
        ),
        "ru": (
            "Примечание: разрешение класса {command} действует только для этой задачи "
            "и сеанса, а не глобально."
        ),
        "es": (
            "Nota: la autorización de clase {command} solo se aplica a esta tarea "
            "y sesión; no es global."
        ),
        "pt": (
            "Nota: a autorização da classe {command} vale apenas para esta tarefa "
            "e sessão; não é global."
        ),
    },
    "exact_scope": {
        "zh": "说明：此权限仅适用于这一次操作；该操作没有可复用的授权类别。",
        "zh-Hant": "說明：此權限僅適用於這一次操作；該操作沒有可重用的授權類別。",
        "en": "Note: this grant is per-invocation; no reusable command class is available.",
        "ja": "注: この許可は今回の呼び出しのみ有効です。再利用可能なコマンド分類はありません。",
        "ko": "참고: 이 권한은 이번 호출에만 적용되며 재사용 가능한 명령 유형이 없습니다.",
        "ru": (
            "Примечание: разрешение действует только для этого вызова; "
            "повторно используемого класса нет."
        ),
        "es": "Nota: este permiso es por invocación; no hay una clase de comando reutilizable.",
        "pt": "Nota: esta permissão vale por chamada; não há uma classe de comando reutilizável.",
    },
    "id": {
        "zh": "审批 ID",
        "zh-Hant": "審批 ID",
        "en": "Approval ID",
        "ja": "承認 ID",
        "ko": "승인 ID",
        "ru": "ID разрешения",
        "es": "ID de aprobación",
        "pt": "ID da aprovação",
    },
    "tool": {
        "zh": "请求的工具/动作",
        "zh-Hant": "請求的工具/動作",
        "en": "Requested tool/action",
        "ja": "要求されたツール/操作",
        "ko": "요청된 도구/작업",
        "ru": "Запрошенный инструмент/действие",
        "es": "Herramienta/acción solicitada",
        "pt": "Ferramenta/ação solicitada",
    },
    "scope": {
        "zh": "资源范围",
        "zh-Hant": "資源範圍",
        "en": "Resource scope",
        "ja": "リソース範囲",
        "ko": "리소스 범위",
        "ru": "Область ресурса",
        "es": "Alcance del recurso",
        "pt": "Escopo do recurso",
    },
    "task": {
        "zh": "当前任务",
        "zh-Hant": "目前任務",
        "en": "Current task",
        "ja": "現在のタスク",
        "ko": "현재 작업",
        "ru": "Текущая задача",
        "es": "Tarea actual",
        "pt": "Tarefa atual",
    },
    "source": {
        "zh": "请求来源",
        "zh-Hant": "請求來源",
        "en": "Request source",
        "ja": "要求元",
        "ko": "요청 출처",
        "ru": "Источник запроса",
        "es": "Origen de la solicitud",
        "pt": "Origem da solicitação",
    },
    "requested_by": {
        "zh": "请求者",
        "zh-Hant": "請求者",
        "en": "Requested by",
        "ja": "要求者",
        "ko": "요청자",
        "ru": "Запросил",
        "es": "Solicitado por",
        "pt": "Solicitado por",
    },
    "expires": {
        "zh": "过期时间",
        "zh-Hant": "過期時間",
        "en": "Expires",
        "ja": "期限",
        "ko": "만료",
        "ru": "Истекает",
        "es": "Caduca",
        "pt": "Expira",
    },
    "approved_once": {
        "zh": "已同意本轮审批 {approval_id}",
        "zh-Hant": "已同意本輪審批 {approval_id}",
        "en": "Approved this turn {approval_id}",
        "ja": "このターンを承認しました {approval_id}",
        "ko": "이번 대화를 승인했습니다 {approval_id}",
        "ru": "Одобрено для этого хода {approval_id}",
        "es": "Aprobado para este turno {approval_id}",
        "pt": "Aprovado para esta rodada {approval_id}",
    },
    "approved_similar": {
        "zh": "已同意此类审批 {approval_id}",
        "zh-Hant": "已同意此類審批 {approval_id}",
        "en": "Approved this similar class {approval_id}",
        "ja": "この同種の操作を承認しました {approval_id}",
        "ko": "같은 유형을 승인했습니다 {approval_id}",
        "ru": "Похожий класс одобрен {approval_id}",
        "es": "Clase similar aprobada {approval_id}",
        "pt": "Classe similar aprovada {approval_id}",
    },
    "rejected": {
        "zh": "已拒绝审批 {approval_id}",
        "zh-Hant": "已拒絕審批 {approval_id}",
        "en": "Rejected approval {approval_id}",
        "ja": "承認を拒否しました {approval_id}",
        "ko": "승인을 거부했습니다 {approval_id}",
        "ru": "Разрешение отклонено {approval_id}",
        "es": "Aprobación rechazada {approval_id}",
        "pt": "Aprovação rejeitada {approval_id}",
    },
    "missing": {
        "zh": "找不到审批记录：{approval_id}",
        "zh-Hant": "找不到審批記錄：{approval_id}",
        "en": "Approval record not found: {approval_id}",
        "ja": "承認記録が見つかりません: {approval_id}",
        "ko": "승인 기록을 찾을 수 없습니다: {approval_id}",
        "ru": "Запись разрешения не найдена: {approval_id}",
        "es": "Registro de aprobación no encontrado: {approval_id}",
        "pt": "Registro de aprovação não encontrado: {approval_id}",
    },
    "resuming": {
        "zh": "审批已记录，正在继续当前会话…",
        "zh-Hant": "審批已記錄，正在繼續目前會話…",
        "en": "Approval recorded. Resuming the current session...",
        "ja": "承認を記録しました。現在のセッションを再開します...",
        "ko": "승인을 기록했습니다. 현재 세션을 계속합니다...",
        "ru": "Разрешение записано. Продолжаю текущую сессию...",
        "es": "Aprobación registrada. Reanudando la sesión actual...",
        "pt": "Aprovação registrada. Retomando a sessão atual...",
    },
    "already_resumed": {
        "zh": "审批已处理，当前会话已继续。",
        "zh-Hant": "審批已處理，目前會話已繼續。",
        "en": "Approval already handled; the current session has resumed.",
        "ja": "承認は処理済みで、現在のセッションは再開されています。",
        "ko": "승인이 이미 처리되어 현재 세션이 계속되었습니다.",
        "ru": "Разрешение уже обработано, текущая сессия продолжена.",
        "es": "La aprobación ya fue procesada; la sesión actual continuó.",
        "pt": "A aprovação já foi processada; a sessão atual continuou.",
    },
    "resume_content": {
        "zh": "继续",
        "zh-Hant": "繼續",
        "en": "Continue",
        "ja": "続けて",
        "ko": "계속",
        "ru": "Продолжить",
        "es": "Continuar",
        "pt": "Continuar",
    },
    "approved_once_reason": {
        "zh": "CLI 用户同意，仅限本轮对话",
        "zh-Hant": "CLI 使用者同意，僅限本輪對話",
        "en": "CLI user approved for this turn only",
        "ja": "CLI ユーザーがこのターンのみ承認",
        "ko": "CLI 사용자가 이번 대화만 승인",
        "ru": "Пользователь CLI одобрил только для этого хода",
        "es": "Usuario CLI aprobó solo para este turno",
        "pt": "Usuário CLI aprovou somente esta rodada",
    },
    "approved_similar_reason": {
        "zh": "CLI 用户同意当前任务内同类操作",
        "zh-Hant": "CLI 使用者同意目前任務內同類操作",
        "en": "CLI user approved the similar class within the current task",
        "ja": "CLI ユーザーが現在のタスク内の同種操作を承認",
        "ko": "CLI 사용자가 현재 작업 내 같은 유형을 승인",
        "ru": "Пользователь CLI одобрил похожий класс в текущей задаче",
        "es": "Usuario CLI aprobó la clase similar dentro de la tarea actual",
        "pt": "Usuário CLI aprovou a classe similar dentro da tarefa atual",
    },
    "rejected_reason": {
        "zh": "CLI 用户拒绝",
        "zh-Hant": "CLI 使用者拒絕",
        "en": "CLI user denied",
        "ja": "CLI ユーザーが拒否",
        "ko": "CLI 사용자가 거부",
        "ru": "Пользователь CLI отклонил",
        "es": "Usuario CLI rechazó",
        "pt": "Usuário CLI negou",
    },
}


def _normalize_pasted_text(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _input_line_count(content: str) -> int:
    if not content:
        return 1
    return content.count("\n") + 1


def _collapsed_paste_placeholder(line_count: int) -> str:
    language = _current_cli_language()
    placeholders = {
        "zh": f"[用户输入 {line_count} 行]",
        "zh-Hant": f"[使用者輸入 {line_count} 行]",
        "en": f"[user input {line_count} lines]",
        "ja": f"[ユーザー入力 {line_count} 行]",
        "ko": f"[사용자 입력 {line_count}줄]",
        "ru": f"[ввод пользователя: {line_count} строк]",
        "es": f"[entrada del usuario: {line_count} líneas]",
        "pt": f"[entrada do usuário: {line_count} linhas]",
    }
    return placeholders.get(language, placeholders["en"])


class _CollapsedPasteState:
    def __init__(self) -> None:
        self._pastes: list[tuple[str, str]] = []

    def collapse(self, content: str) -> str:
        line_count = _input_line_count(content)
        placeholder = _collapsed_paste_placeholder(line_count)
        self._pastes.append((placeholder, content))
        return placeholder

    def placeholders(self) -> list[str]:
        return [placeholder for placeholder, _ in self._pastes]

    def placeholder_span(
        self, content: str, cursor_position: int, *, backward: bool
    ) -> tuple[int, int] | None:
        for placeholder in self.placeholders():
            start = content.find(placeholder)
            while start >= 0:
                end = start + len(placeholder)
                if backward and start < cursor_position <= end:
                    return start, end
                if not backward and start <= cursor_position < end:
                    return start, end
                start = content.find(placeholder, start + len(placeholder))
        return None

    def expand(self, content: str) -> str:
        expanded: list[str] = []
        position = 0
        for placeholder, paste in self._pastes:
            start = content.find(placeholder, position)
            if start < 0:
                break
            expanded.append(content[position:start])
            expanded.append(paste)
            position = start + len(placeholder)
        expanded.append(content[position:])
        return "".join(expanded)


class _CollapsedPasteProcessor(Processor):
    def __init__(self, paste_state: _CollapsedPasteState) -> None:
        self._paste_state = paste_state

    def apply_transformation(self, transformation_input):
        fragments = []
        placeholders = self._paste_state.placeholders()
        if not placeholders:
            return Transformation(transformation_input.fragments)
        for fragment in transformation_input.fragments:
            style, text, *rest = fragment
            position = 0
            while position < len(text):
                match = _next_placeholder(text, placeholders, position)
                if match is None:
                    fragments.append((style, text[position:], *rest))
                    break
                start, end = match
                if start > position:
                    fragments.append((style, text[position:start], *rest))
                fragments.append((f"{style} fg:{_PURPLE} bold", text[start:end], *rest))
                position = end
        return Transformation(fragments)


def _next_placeholder(
    content: str, placeholders: list[str], position: int
) -> tuple[int, int] | None:
    matches = [
        (start, start + len(placeholder))
        for placeholder in placeholders
        if (start := content.find(placeholder, position)) >= 0
    ]
    if not matches:
        return None
    return min(matches, key=lambda match: match[0])


def _chat_key_bindings(paste_state: _CollapsedPasteState) -> KeyBindings:
    bindings = KeyBindings()

    def marker_before_cursor() -> bool:
        buffer = get_app().current_buffer
        return (
            paste_state.placeholder_span(
                buffer.text, buffer.cursor_position, backward=True
            )
            is not None
        )

    def marker_at_cursor() -> bool:
        buffer = get_app().current_buffer
        return (
            paste_state.placeholder_span(
                buffer.text, buffer.cursor_position, backward=False
            )
            is not None
        )

    @bindings.add(Keys.BracketedPaste)
    def _paste(event) -> None:
        data = _normalize_pasted_text(event.data)
        if _input_line_count(data) > 4:
            data = paste_state.collapse(data)
        event.current_buffer.insert_text(data)

    @bindings.add("backspace", filter=Condition(marker_before_cursor))
    @bindings.add("c-h", filter=Condition(marker_before_cursor))
    def _delete_collapsed_paste_before_cursor(event) -> None:
        buffer = event.current_buffer
        span = paste_state.placeholder_span(
            buffer.text, buffer.cursor_position, backward=True
        )
        if span is None:
            return
        start, end = span
        buffer.cursor_position = start
        buffer.delete(end - start)

    @bindings.add("delete", filter=Condition(marker_at_cursor))
    def _delete_collapsed_paste_at_cursor(event) -> None:
        buffer = event.current_buffer
        span = paste_state.placeholder_span(
            buffer.text, buffer.cursor_position, backward=False
        )
        if span is None:
            return
        start, end = span
        buffer.cursor_position = start
        buffer.delete(end - start)

    @bindings.add("left", filter=Condition(marker_before_cursor))
    def _skip_collapsed_paste_left(event) -> None:
        buffer = event.current_buffer
        span = paste_state.placeholder_span(
            buffer.text, buffer.cursor_position, backward=True
        )
        if span is not None:
            buffer.cursor_position = span[0]

    @bindings.add("right", filter=Condition(marker_at_cursor))
    def _skip_collapsed_paste_right(event) -> None:
        buffer = event.current_buffer
        span = paste_state.placeholder_span(
            buffer.text, buffer.cursor_position, backward=False
        )
        if span is not None:
            buffer.cursor_position = span[1]

    return bindings


def _sprout_system_prompt() -> str:
    return _L(
        "你是 SEAM Sprout，一个面向软件项目的自进化 AI 运行时。"
        "当用户询问你是谁、能做什么或功能时，请用 SEAM Sprout 的身份介绍"
        "项目分析、代码生成、隔离执行、验证、集成，以及任务、存储、日志、"
        "模型和 Web 控制台管理能力。",
        "You are SEAM Sprout, a self-evolving AI runtime for software projects. "
        "When users ask who you are or what you can do, answer as SEAM Sprout and "
        "describe project analysis, code generation, isolated execution, "
        "verification, integration, and task/storage/log/model/web management.",
    )


def _hints() -> dict[str, str]:
    """Return command hints in the active CLI language."""
    return {
        "/storage": _L(
            "运行 `sprout storage status` 查看数据库状态",
            "Run `sprout storage status`",
        ),
        "/session": _L(
            "运行 `sprout session --help` 查看会话操作",
            "Run `sprout session --help`",
        ),
        "/db": _L(
            "运行 `sprout db --help` 查看统一数据库操作",
            "Run `sprout db --help`",
        ),
        "/db status": _L(
            "运行 `sprout db status` 查看数据库状态",
            "Run `sprout db status`",
        ),
        "/db backup": _L(
            "运行 `sprout db backup <target>` 备份数据库",
            "Run `sprout db backup <target>`",
        ),
        "/db init": _L(
            "运行 `sprout db init` 初始化数据库",
            "Run `sprout db init`",
        ),
        "/db restore": _L(
            "运行 `sprout db restore <source>` 恢复数据库",
            "Run `sprout db restore <source>`",
        ),
        "/db session-new": _L(
            "运行 `sprout db session-new --user <id>` 新建会话",
            "Run `sprout db session-new --user <id>`",
        ),
        "/db session-history": _L(
            "运行 `sprout db session-history <id>` 查看会话",
            "Run `sprout db session-history <id>`",
        ),
        "/db session-search": _L(
            "运行 `sprout db session-search <query>` 搜索会话",
            "Run `sprout db session-search <query>`",
        ),
        "/db session-delete": _L(
            "运行 `sprout db session-delete <id>` 删除会话",
            "Run `sprout db session-delete <id>`",
        ),
        "/info": _L(
            "运行 `sprout info` 查看运行时",
            "Run `sprout info`",
        ),
        "/mcp": _L(
            "运行 `sprout mcp --help` 查看 MCP",
            "Run `sprout mcp --help`",
        ),
        "/memory": _L(
            "运行 `sprout memory --help`",
            "Run `sprout memory --help`",
        ),
        "/project": _L(
            "运行 `sprout project --help`",
            "Run `sprout project --help`",
        ),
        "/remote": _L(
            "运行 `sprout remote --help`",
            "Run `sprout remote --help`",
        ),
        "/evolution": _L(
            "运行 `sprout evolution --help`",
            "Run `sprout evolution --help`",
        ),
        "/approvals": _L(
            "运行 `sprout approvals --help`",
            "Run `sprout approvals --help`",
        ),
        "/audit": _L(
            "运行 `sprout audit --help`",
            "Run `sprout audit --help`",
        ),
        "/serve": _L(
            "运行 `sprout serve`",
            "Run `sprout serve`",
        ),
        "/orchestrator": _L(
            "运行 `sprout orchestrator worker`",
            "Run `sprout orchestrator worker`",
        ),
    }


def _print_reply_meta(metadata) -> None:
    model = metadata.get("model") if hasattr(metadata, "get") else None
    steps = metadata.get("steps") if hasattr(metadata, "get") else None
    usage = metadata.get("usage") if hasattr(metadata, "get") else None
    if usage is None:
        return
    try:
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
    except AttributeError:
        return
    parts = [
        _L(f"模型={model or 'unknown'}", f"model={model or 'unknown'}"),
        _L(f"步骤={steps or 1}", f"steps={steps or 1}"),
        _L(
            f"输入={prompt} 输出={completion} 总计={total}",
            f"tokens={prompt}+{completion}={total}",
        ),
    ]
    typer.echo(ui.muted("  " + " · ".join(parts)))


def _print_model_usage(response=None, *, model: str | None = None, usage=None) -> None:
    """Print model and token usage for the just-completed direct chat turn."""
    if usage is None and response is not None:
        usage = response.usage
    usage = usage or Usage()
    if model is None and response is not None:
        model = response.model
    prompt = getattr(usage, "prompt_tokens", 0)
    completion = getattr(usage, "completion_tokens", 0)
    total = getattr(usage, "total_tokens", prompt + completion)
    model = model or "unknown"
    typer.echo(
        ui.muted(
            _L(
                f"  模型={model} · 输入={prompt} · 输出={completion} · 总计={total}",
                f"  model={model} · input={prompt} · output={completion} · total={total}",
            )
        )
    )


def _print_session_separator() -> None:
    line = "-" * 72
    typer.echo(ui.text(line, fg=ui.PURPLE, bold=True))


def _completion_style() -> Style:
    """Shared completion menu styling: no backgrounds, purple selected item."""
    return Style.from_dict(
        {
            "completion-menu": "bg:default",
            "completion-menu.completion": "bg:default",
            "completion-menu.completion.current": f"bg:default fg:{_PURPLE} bold",
            "completion-menu.meta.completion": "bg:default fg:ansidefault",
            "completion-menu.meta.completion.current": "bg:default fg:ansidefault",
            "scrollbar": "bg:default",
            "scrollbar.background": "bg:default",
            "scrollbar.button": "bg:default",
            "scrollbar.arrow": "bg:default",
        }
    )


def _select_style() -> Style:
    """Shared questionary select styling: purple highlighted text without a background."""
    return approval_select_style()


async def _readline_with_slash_hint() -> str:
    """Read one line with prompt_toolkit and live slash suggestions."""
    paste_state = _CollapsedPasteState()
    session = PromptSession(
        history=_CHAT_HISTORY,
        completer=SlashCompleter(),
        complete_while_typing=True,
        complete_style=CompleteStyle.COLUMN,
        reserve_space_for_menu=8,
        input_processors=[_CollapsedPasteProcessor(paste_state)],
        key_bindings=_chat_key_bindings(paste_state),
        style=_completion_style(),
    )

    try:
        answer = await session.prompt_async("> ")
    except (EOFError, KeyboardInterrupt):
        raise
    return paste_state.expand(answer).strip()


class SlashCompleter(Completer):
    """Offer slash commands as an interactive completion menu."""

    def get_completions(self, document, complete_event):
        text = document.text
        if not text.startswith("/"):
            return
        terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns

        if text.startswith("/language "):
            command = text.split(" ", 1)[0]
            prefix = text[len(command) + 1 :]
            for language in _supported_languages():
                if language.startswith(prefix):
                    display_text = f"  {language:<12}{_language_name(language)}"
                    yield Completion(
                        f"{command} {language}",
                        start_position=-len(text),
                        display=display_text.ljust(
                            max(terminal_width - 2, len(display_text))
                        ),
                        display_meta="",
                    )
            return

        if text.startswith("/gateway "):
            prefix = text[len("/gateway ") :]
            for command, description in _gateway_subcommands():
                if command.startswith(prefix):
                    display_text = f"  {command:<12}{description}"
                    yield Completion(
                        f"/gateway {command}",
                        start_position=-len(text),
                        display=display_text.ljust(
                            max(terminal_width - 2, len(display_text))
                        ),
                        display_meta="",
                    )
            return

        for command, description in _slash_rows():
            if command.startswith(text):
                display_text = f"{command:<11}{description}"
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=display_text.ljust(max(terminal_width - 2, len(display_text))),
                    display_meta="",
                )


_SLASH_ROWS = [
    ("/", "显示所有可用命令", "Show all available commands"),
    ("/help", "显示命令列表及详细说明", "Show command list and details"),
    ("/language", "切换界面语言", "Switch UI language"),
    ("/clear", "清空当前终端屏幕", "Clear current terminal screen"),
    ("/chat", "返回普通对话模式，继续输入消息", "Return to normal chat mode"),
    ("/storage", "查看本地数据库连接和状态", "Inspect local database health and status"),
    ("/session", "搜索、查看、压缩或删除会话", "Search, view, compact, or delete sessions"),
    ("/stop", "停止当前会话", "Stop current session"),
    ("/db", "统一数据库操作", "Unified database operations"),
    ("/info", "运行时与配置", "Runtime and config"),
    ("/mcp", "MCP 服务", "MCP server"),
    ("/memory", "记忆管理", "Memory management"),
    ("/skill", "技能管理", "Skill management"),
    ("/project", "项目操作", "Project operations"),
    ("/task", "提交一个后台 coding 任务", "Submit a background coding task"),
    ("/status", "查询后台任务状态", "Check a background task status"),
    ("/remote", "远程操作", "Remote operations"),
    ("/evolution", "成长平面", "Evolution"),
    ("/approvals", "审批操作", "Approvals"),
    ("/audit", "审计验证", "Audit verification"),
    ("/serve", "启动 Web 控制台", "Start web console"),
    ("/web", "打开 Web 控制台", "Open web console"),
    ("/orchestrator", "Temporal 任务 worker", "Temporal worker"),
    ("/model", "切换模型", "Switch model"),
    ("/gateway", "配置外部消息网关", "Configure external messaging gateway"),
    ("/exit", "结束当前 CLI 对话", "Exit the current CLI chat"),
]

_GATEWAY_SUBCOMMANDS = [
    ("feishu", "配置飞书", "Configure Feishu"),
    ("wechat-ilink", "配置微信 iLink", "Configure WeChat iLink"),
]


def _slash_rows() -> list[tuple[str, str]]:
    return [
        (command, _L(zh, en))
        for command, zh, en in _SLASH_ROWS
    ]


def _gateway_subcommands() -> list[tuple[str, str]]:
    return [
        (command, _L(zh, en))
        for command, zh, en in _GATEWAY_SUBCOMMANDS
    ]


def _show_gateway_directory() -> None:
    """Show gateway setup options inside the chat TUI."""
    typer.echo(ui.text(_L("网关配置", "Gateway setup"), bold=True))
    for command, description in _gateway_subcommands():
        typer.echo(ui.bullet(f"/gateway {command}", description))


#: ``/skill`` sub-commands: (name, 中文描述, English description, required args).
#: ``None`` means the sub-command takes no positional argument.
_SKILL_SUBCOMMANDS = [
    ("list", "列出技能注册表", "List the skill registry", None),
    ("menu", "进入分层 Skill 菜单", "Enter the hierarchical Skill menu", None),
    (
        "search",
        "搜索技能源（只读，不下载）",
        "Search a source (read-only)",
        "<query> [-s source]",
    ),
    (
        "find",
        "查找技能：已装的优先，--crawl 时搜远端",
        "Find a skill: installed first, remote with --crawl",
        "<query> [--crawl]",
    ),
    (
        "install",
        "安装技能（走策略引擎与审批）",
        "Install a skill (policy + approval)",
        "<locator> [-s source]",
    ),
    (
        "import",
        "从本机目录导入技能（递归扫描，免审批）",
        "Import skills from a local directory (recursive, no approval)",
        "<path> [--dry-run]",
    ),
    (
        "forget",
        "删除技能注册表记录（不动文件）",
        "Drop a skill's registry row (leaves files)",
        "<name>",
    ),
    (
        "crawl",
        "从配置的站点刷新候选缓存",
        "Refresh the candidate cache from configured sites",
        None,
    ),
    (
        "index",
        "查看或重建本地索引快照",
        "Show or rebuild the local index snapshot",
        None,
    ),
]


def _skill_subcommands() -> list[tuple[str, str]]:
    return [(command, _L(zh, en)) for command, zh, en, _ in _SKILL_SUBCOMMANDS]


def _skill_required_args() -> dict[str, str | None]:
    return {command: required for command, _, _, required in _SKILL_SUBCOMMANDS}


def _show_skill_directory() -> None:
    """Show the skill sub-commands inside the chat TUI."""
    typer.echo(ui.text(_L("技能管理", "Skill management"), bold=True))
    for command, description in _skill_subcommands():
        typer.echo(ui.bullet(command, description))


async def _prompt_skill_subcommand() -> str:
    """Select a second-level Skill command after entering ``/skill``."""
    choices = [
        questionary.Choice(f"{command}  {description}", value=command)
        for command, description in _skill_subcommands()
    ]
    choices.append(questionary.Choice("done  返回一级菜单", value=""))
    try:
        selected = await questionary.select(
            _L("请选择", "Choose"),
            choices=choices,
            style=_select_style(),
        ).ask_async()
    except (EOFError, KeyboardInterrupt):
        return ""
    return selected or ""


async def _handle_skill_command(content: str) -> None:
    """``/skill`` — print the skill directory, or forward to ``sprout skills``.

    Bare ``/skill`` shows the sub-commands plus what is already installed;
    anything else is handed to the ``sprout skills`` CLI, so
    ``/skill install <src>`` inherits the same policy engine and approval flow
    as the command line (design §7.4) — the TUI adds no second mechanism.

    Sub-commands and their required arguments are checked here: a bare
    ``/skill search`` would otherwise fall through to Typer's raw
    ``Missing argument 'query'`` panel, which reads like a crash rather than a
    prompt for input.
    """
    _, _, rest = content.partition(" ")
    rest = rest.strip()
    if not rest:
        if sys.stdin.isatty():
            selected = await _prompt_skill_subcommand()
            if selected:
                await _handle_skill_command(f"/skill {selected}")
            return
        await _stream_sprout_command(["skills", "list"])
        return
    try:
        arguments = shlex.split(rest)
    except ValueError:
        typer.echo(
            ui.warning(
                _L(
                    "参数无法解析，请检查引号是否成对",
                    "Could not parse arguments; check for unbalanced quotes",
                )
            )
        )
        return
    known = _skill_required_args()
    name = arguments[0]
    if name not in known:
        typer.echo(ui.warning(f"{_L('未知子命令', 'Unknown sub-command')}: {name}"))
        _show_skill_directory()
        return
    required = known[name]
    if required and len(arguments) == 1:
        typer.echo(ui.warning(f"{_L('用法', 'Usage')}: /skill {name} {required}"))
        typer.echo(
            ui.muted(
                _L(
                    "提示：加 --help 查看完整参数",
                    "Tip: add --help for the full argument list",
                )
            )
        )
        return
    await _stream_sprout_command(["skills", *arguments])


async def _prompt_gateway_subcommand() -> str:
    """Prompt for a gateway subcommand with up/down selection."""
    try:
        selected = await questionary.select(
            _L("网关配置", "Gateway setup"),
            choices=[
                questionary.Choice(
                    f"{'feishu':<15}{_L('配置飞书', 'Configure Feishu')}",
                    "feishu",
                ),
                questionary.Choice(
                    f"{'wechat-ilink':<15}{_L('配置微信 iLink', 'Configure WeChat iLink')}",
                    "wechat-ilink",
                ),
                questionary.Choice(
                    f"{'done':<15}{_L('返回一级', 'Return to main menu')}",
                    "",
                ),
            ],
            style=_select_style(),
        ).ask_async()
    except (EOFError, KeyboardInterrupt):
        return ""
    return selected or ""


async def _prompt_language_subcommand() -> str:
    """Prompt for a supported CLI language."""
    choices = [
        questionary.Choice(
            f"{language:<12}{_language_name(language)}",
            language,
        )
        for language in _supported_languages()
    ]
    choices.append(
        questionary.Choice(
            f"{'done':<12}{_L('返回一级', 'Return to main menu')}",
            "",
        )
    )
    try:
        selected = await questionary.select(
            _L("切换界面语言", "Switch UI language"),
            choices=choices,
            style=_select_style(),
        ).ask_async()
    except (EOFError, KeyboardInterrupt):
        return ""
    return selected or ""


def _port_is_open(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex((host, port)) == 0


async def _ensure_web_server(host: str, port: int) -> tuple[bool, bool]:
    """Return ``(ready, started_now)`` and start the web server if needed."""
    global _WEB_PROCESS
    if await asyncio.to_thread(_port_is_open, host, port):
        return True, False

    if _WEB_PROCESS is None or _WEB_PROCESS.returncode is not None:
        _WEB_PROCESS = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "Sprout.cli.app",
            "serve",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    for _ in range(80):
        if _WEB_PROCESS.returncode is not None:
            break
        if await asyncio.to_thread(_port_is_open, host, port):
            return True, True
        await asyncio.sleep(0.25)
    return False, True


class GatewaySubCompleter(Completer):
    """Second-level completions for gateway setup."""

    def get_completions(self, document, complete_event):
        text = document.text
        terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns
        for command, description in _gateway_subcommands():
            if command.startswith(text):
                display_text = f"{command:<12}{description}"
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=display_text.ljust(max(terminal_width - 2, len(display_text))),
                    display_meta="",
                )


async def _setup_gateway_in_chat(channel: str) -> bool:
    """Configure one external gateway from inside the interactive chat."""
    from Sprout.cli.commands.gateway import (
        WeixinIlinkClient,
        _resolve_weixin_paths,
        _setup_weixin_ilink,
    )
    from Sprout.config.loader import load_settings

    settings = load_settings()
    if channel == "feishu":
        return await _manage_feishu(settings)
    else:
        accounts_path, _ = _resolve_weixin_paths(settings, None)
        client = WeixinIlinkClient(base_url=settings.weixin_ilink.base_url)
        return await _setup_weixin_ilink(client, accounts_path)


async def _manage_feishu(settings) -> bool:
    """Show existing Feishu config and allow overwrite."""
    from Sprout.cli.commands.gateway import _setup_feishu, _show_feishu_existing

    while True:
        action = await questionary.select(
            _L("飞书网关", "Feishu Gateway"),
            choices=[
                questionary.Choice(_L("查看已有配置", "View existing"), "view"),
                questionary.Choice(
                    _L("重新配置并覆盖", "Reconfigure and overwrite"),
                    "reconfigure",
                ),
                questionary.Choice(
                    f"done {_L('返回上一层', 'Return to gateway menu')}",
                    "done",
                ),
            ],
            style=_select_style(),
        ).ask_async()
        if action == "done" or action is None:
            return False
        if action == "view":
            _show_feishu_existing(settings)
            continue
        return _setup_feishu(settings, force=True)


async def _prompt_db_action() -> str | None:
    """Prompt for a database operation."""
    action = await questionary.select(
        _L("数据库操作", "Database operations"),
        choices=[
            questionary.Choice(
                f"status {_L('查看状态', 'Database status')}",
                "status",
            ),
            questionary.Choice(
                f"init {_L('初始化数据库', 'Initialize databases')}",
                "init",
            ),
            questionary.Choice(
                f"backup {_L('备份数据库', 'Backup databases')}",
                "backup",
            ),
            questionary.Choice(
                f"restore {_L('恢复数据库', 'Restore databases')}",
                "restore",
            ),
            questionary.Choice(
                f"session-new {_L('新建会话', 'New session')}",
                "session-new",
            ),
            questionary.Choice(
                f"session-history {_L('查看会话历史', 'Session history')}",
                "session-history",
            ),
            questionary.Choice(
                f"session-search {_L('搜索会话', 'Session search')}",
                "session-search",
            ),
            questionary.Choice(
                f"session-delete {_L('删除会话', 'Delete session')}",
                "session-delete",
            ),
            questionary.Choice(
                f"done {_L('返回一级', 'Return to main menu')}",
                "",
            ),
        ],
        style=_select_style(),
    ).ask_async()
    return action or None


async def _execute_db_action(action: str) -> None:
    """Execute one database action through the unified CLI."""
    args: list[str] = ["db"]
    if action in {"status", "init"}:
        args.append(action)
    elif action == "backup":
        target = await questionary.text(_L("备份目录", "Backup directory")).ask_async()
        if not target:
            return
        args.extend(["backup", target.strip()])
    elif action == "restore":
        source = await questionary.text(
            _L("备份源目录", "Backup source directory")
        ).ask_async()
        if not source:
            return
        target = await questionary.text(
            _L("恢复目标目录（可选）", "Restore target directory (optional)")
        ).ask_async()
        args.extend(["restore", source.strip()])
        if target and target.strip():
            args.extend(["--target", target.strip()])
    elif action == "session-new":
        user = await questionary.text(_L("用户 ID", "User id")).ask_async()
        if not user:
            return
        args.extend(["session-new", "--user", user.strip()])
    elif action == "session-history":
        session_id = await questionary.text(_L("会话 ID", "Session id")).ask_async()
        if not session_id:
            return
        args.extend(["session-history", session_id.strip()])
    elif action == "session-search":
        query = await questionary.text(_L("FTS5 查询", "FTS5 query")).ask_async()
        if not query:
            return
        args.extend(["session-search", query.strip()])
    elif action == "session-delete":
        session_id = await questionary.text(_L("会话 ID", "Session id")).ask_async()
        if not session_id:
            return
        args.extend(["session-delete", session_id.strip()])
    else:
        return

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "Sprout.cli.app",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async def stream(reader, *, muted: bool = False) -> None:
        while True:
            line = await reader.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if muted:
                typer.echo(ui.muted(text))
            else:
                typer.echo(text)

    await asyncio.gather(
        stream(process.stdout),
        stream(process.stderr, muted=True),
    )
    await process.wait()


async def _prompt_model_action() -> None:
    action = await questionary.select(
        _L("模型", "Model"),
        choices=[
            questionary.Choice(_L("查看当前模型", "Show current model"), "list"),
            questionary.Choice(_L("切换模型", "Switch model"), "set"),
            questionary.Choice(
                f"done {_L('返回一级', 'Return to main menu')}",
                "",
            ),
        ],
        style=_select_style(),
    ).ask_async()
    if action == "list":
        from Sprout.cli.commands.model import list_cmd

        list_cmd()
        return
    if action == "set":
        provider = await questionary.select(
            _L("提供商", "Provider"),
            choices=["aiyallm", "openai_compatible", "echo"],
            style=_select_style(),
        ).ask_async()
        if not provider:
            return
        model = await questionary.text(_L("模型名称", "Model name")).ask_async()
        base_url = await questionary.text(_L("基础 URL", "Base URL")).ask_async()
        api_key_env = await questionary.text(
            _L("API Key 环境变量", "API key environment variable")
        ).ask_async()
        if not model or not base_url or not api_key_env:
            return
        await _stream_sprout_command(
            [
                "model",
                "set",
                "--provider",
                provider,
                "--model",
                model.strip(),
                "--base-url",
                base_url.strip(),
                "--api-key-env",
                api_key_env.strip(),
            ]
        )


async def _stream_sprout_command(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "Sprout.cli.app",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream(reader, *, muted: bool = False) -> None:
        while True:
            line = await reader.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if muted:
                typer.echo(ui.muted(text))
            else:
                typer.echo(text)

    await asyncio.gather(
        stream(process.stdout),
        stream(process.stderr, muted=True),
    )
    await process.wait()

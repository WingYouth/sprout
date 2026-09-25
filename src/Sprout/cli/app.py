"""CLI entry: every command goes through the Runtime Factory, never storage."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator

import typer

from Sprout.cli.commands import approvals as approvals_command
from Sprout.cli.commands import audit as audit_command
from Sprout.cli.commands import chat as chat_command
from Sprout.cli.commands import db as db_command
from Sprout.cli.commands import evolution as evolution_command
from Sprout.cli.commands import gateway as gateway_command
from Sprout.cli.commands import mcp as mcp_command
from Sprout.cli.commands import memory as memory_command
from Sprout.cli.commands import model as model_command
from Sprout.cli.commands import orchestrator as orchestrator_command
from Sprout.cli.commands import project as project_command
from Sprout.cli.commands import remote as remote_command
from Sprout.cli.commands import run as run_command
from Sprout.cli.commands import security as security_command
from Sprout.cli.commands import serve as serve_command
from Sprout.cli.commands import session as session_command
from Sprout.cli.commands import skills as skills_command
from Sprout.cli.commands import stop as stop_command
from Sprout.cli.commands import storage as storage_command
from Sprout.cli.commands.info import info
from Sprout.cli.i18n import L as _L
from Sprout.cli.ui import text as ui_text

_QUICK_EXAMPLES = [
    ("sprout", "启动交互式对话", "Start interactive chat"),
    (
        "sprout run \"修复这个 bug\"",
        "当前项目内自动扫描、规划、编码、验证并整合",
        "Run scan, strategy, coding, validation and integration in this project",
    ),
    ("sprout chat \"hello\"", "发送一次性消息", "Send a one-shot message"),
    ("uv run sprout info", "显示版本与生效配置", "Show version and effective settings"),
    ("uv run sprout storage init", "创建本地数据库表结构", "Create local database schemas"),
    ("uv run sprout storage check", "验证每条存储链路", "Prove every storage lane"),
    ("uv run sprout mcp inspect", "检查安全 MCP 服务面", "Inspect MCP server surface"),
    ("uv run sprout approvals list", "显示待审批请求", "Show pending approvals"),
    ("uv run sprout audit verify", "验证安全审计哈希链", "Verify the audit hash chain"),
    (
        "uv run sprout security check",
        "复查安全与权限控制面",
        "Re-check the authorization controls",
    ),
    ("uv run sprout serve", "启动 Web API 与前端", "Start the web API and frontend"),
    ("uv run sprout gateway setup", "扫码登录外部消息通道", "QR-login messaging channel"),
    ("sprout orchestrator worker", "运行 Temporal 任务 worker", "Run the Temporal task worker"),
    (
        "uv run sprout remote workspace-list",
        "列出远程 SEMA 工作区",
        "List remote SEMA workspaces",
    ),
    (
        "uv run sprout project workspaces",
        "列出已登记的工作区",
        "List registered workspaces",
    ),
    (
        "uv run sprout project analyze <workspace>",
        "分析工作区并落库项目知识",
        "Analyze a workspace into project knowledge",
    ),
    (
        "uv run sprout project symbols <workspace>",
        "列出类/函数/方法/测试符号",
        "List classes, functions, methods and tests",
    ),
    (
        "uv run sprout project dependencies <workspace> <path>",
        "追踪某个文件的依赖边",
        "Trace one file's dependency edges",
    ),
]


def _examples_text() -> str:
    width = max(len(command) for command, _, _ in _QUICK_EXAMPLES) + 2
    return "\n".join(
        f"  {command:<{width}}{_L(zh, en)}"
        for command, zh, en in _QUICK_EXAMPLES
    )


_CONFIG_TEXT = _L(
    "使用项目旁的 sprout.toml，或设置 SPROUT_CONFIG 指向配置文件。",
    "Use sprout.toml next to the project, or set SPROUT_CONFIG to its path.",
)


EPILOG = (
    f"{ui_text(_L('快速示例', 'Quick examples'), bold=True)}\n"
    f"{_examples_text()}\n\n"
    f"{ui_text(_L('配置', 'Configuration'), bold=True)}\n"
    f"  {_CONFIG_TEXT}"
)

app = typer.Typer(
    name="sprout",
    help=_L(
        "运行并管理 SEAM_Sprout agent 运行时。",
        "Run and manage the SEAM_Sprout agent runtime.",
    ),
    rich_markup_mode="rich",
    epilog=EPILOG,
)

@app.callback(invoke_without_command=True)
def default_command(ctx: typer.Context) -> None:
    """Start an interactive chat when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        chat_command.chat()

app.command()(chat_command.chat)
app.command(name="run")(run_command.run)
app.command()(serve_command.serve)
app.command()(info)
app.add_typer(mcp_command.app, name="mcp")
app.add_typer(model_command.app, name="model")
app.add_typer(orchestrator_command.app, name="orchestrator")
app.add_typer(gateway_command.app, name="gateway")
app.add_typer(db_command.app, name="db")
app.add_typer(memory_command.app, name="memory")
app.add_typer(project_command.app, name="project")
app.add_typer(session_command.app, name="session")
app.add_typer(remote_command.app, name="remote")
app.add_typer(storage_command.app, name="storage")
app.add_typer(evolution_command.app, name="evolution")
app.add_typer(approvals_command.app, name="approvals")
app.add_typer(skills_command.app, name="skills")
app.add_typer(audit_command.app, name="audit")
app.add_typer(security_command.app, name="security")
app.add_typer(stop_command.app, name="stop")


@contextlib.contextmanager
def boot_output_to_stderr() -> Iterator[None]:
    """Keep boot chatter on stderr.

    ``ensure_sprout_home()`` announces itself with ``print()``. That is fine for
    a human, but it lands *before* the payload of every command, so
    ``sprout ... --json`` produced a stream that no consumer could parse (and
    JSON mode is promised by the CLI exposure rules). Boot announcements are
    diagnostics: send them to stderr and leave stdout to the command.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _configure_console_encoding() -> None:
    """Reconfigure non-UTF-8 standard streams so Chinese text stays readable.

    macOS and Linux already use UTF-8; Windows consoles commonly default to
    ``cp936`` or ``gbk`` and would render the CLI's Chinese output as mojibake.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        if encoding and encoding.lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):  # pragma: no cover
                continue


def main() -> None:
    _configure_console_encoding()

    # gRPC writes INFO-level fork diagnostics directly to stderr, outside
    # Sprout's subprocess capture. Keep warnings and errors, suppress chatter.
    os.environ["GRPC_VERBOSITY"] = "ERROR"

    from Sprout.config.loader import load_env_file
    from Sprout.config.sprout_home import ensure_sprout_home

    with boot_output_to_stderr():
        load_env_file()
        ensure_sprout_home()
    app()


if __name__ == "__main__":
    main()

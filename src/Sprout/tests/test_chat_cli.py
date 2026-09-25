"""CLI chat presentation helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from rich.markdown import Markdown

from Sprout.cli.commands import chat
from Sprout.cli.commands.chat import (
    _APPROVAL_TEXT,
    _CLI_CODE_THEME,
    _CLI_MARKDOWN_THEME,
    _approval_text,
    _cli_model_text,
    _CLIStreamPreview,
    _render_cli_markdown_text,
    _skill_required_args,
    _skill_subcommands,
    _slash_rows,
)


def test_cli_model_text_preserves_markdown_for_renderer() -> None:
    assert _cli_model_text("请提供 **工作区**。") == "请提供 **工作区**。"


def test_current_directory_question_uses_the_process_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    answer = chat._current_directory_answer("当前在哪个目录？")

    assert answer == f"当前 CLI 进程目录：{tmp_path.resolve()}"
    assert chat._current_directory_answer("帮我查看当前目录下的文件") is None


def test_cli_markdown_renderer_removes_source_markers() -> None:
    text = "# 标题\n\n说明 **重点**\n\n```python\nprint('**keep**')\n```"

    rendered = _render_cli_markdown_text(text)
    assert "**重点**" not in rendered
    assert "标题" in rendered
    assert "重点" in rendered
    assert "print('**keep**')" in rendered


def test_cli_inline_code_uses_green_text_without_background() -> None:
    import io

    output = io.StringIO()
    Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        theme=_CLI_MARKDOWN_THEME,
    ).print(Markdown("运行 `sprout info`"), end="")

    rendered = output.getvalue()

    assert "\x1b[38;2;52;211;153m" in rendered
    assert "\x1b[48;" not in rendered


def test_cli_code_block_uses_muted_red_background_and_nonbold_green_text() -> None:
    import io

    output = io.StringIO()
    Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        theme=_CLI_MARKDOWN_THEME,
    ).print(Markdown("```python\nprint('ok')\n```", code_theme=_CLI_CODE_THEME), end="")

    rendered = output.getvalue()

    assert "\x1b[48;2;51;33;38m" in rendered
    assert "\x1b[38;2;52;211;153;48;2;51;33;38m" in rendered
    assert "\x1b[1m" not in rendered


def test_cli_markdown_table_headers_use_green() -> None:
    import io

    output = io.StringIO()
    Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        theme=_CLI_MARKDOWN_THEME,
    ).print(Markdown("| 名称 | 状态 |\n| --- | --- |\n| sprout | ok |"), end="")

    rendered = output.getvalue()

    assert "\x1b[38;2;52;211;153m" in rendered


def test_cli_ordered_list_numbers_are_white() -> None:
    import io

    output = io.StringIO()
    Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        theme=_CLI_MARKDOWN_THEME,
    ).print(Markdown("1. 第一项\n2. 第二项\n3. 第三项"), end="")

    rendered = output.getvalue()

    assert "\x1b[37m 1 " in rendered
    assert "\x1b[37m 2 " in rendered
    assert "\x1b[37m 3 " in rendered


def test_stream_preview_handles_split_emphasis_markers() -> None:
    preview = _CLIStreamPreview()
    rendered = preview.process("请提供 *") + preview.process("*工作区")

    assert rendered.plain == "请提供 工作区"


def test_approval_prompt_text_covers_all_supported_languages() -> None:
    languages = {"zh", "zh-Hant", "en", "ja", "ko", "ru", "es", "pt"}

    for key, translations in _APPROVAL_TEXT.items():
        assert languages <= set(translations), key


def test_approval_prompt_explains_permission_scope(monkeypatch) -> None:
    """The scope note has to match the choice beside it.

    It used to promise a wide "whole class" choice while the note said the
    grant stayed on "the same argument fingerprint" — the two contradicted each
    other, and the note was the true one: answering "this class" re-asked for
    the very next subcommand.
    """
    monkeypatch.setenv("SPROUT_CLI_LANG", "en")

    class_text = _approval_text("similar_scope", command="sprout")

    assert "sprout" in class_text, "the class note must name what it covers"
    assert "this task" in class_text, "a class grant is still task-bound"
    assert "not a global grant" in class_text
    assert "fingerprint" not in class_text, "a name grant is not fingerprint-bound"


async def test_cli_workspace_confirmation_binds_current_directory_once(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chat.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    prompted = {}

    class _Prompt:
        async def ask_async(self):
            return "current"

    def _select(message, *, choices, **_kwargs):
        prompted["message"] = message
        prompted["choices"] = choices
        return _Prompt()

    monkeypatch.setattr(chat.questionary, "select", _select)

    class _Runtime:
        async def open_workspace(self, root):
            prompted["root"] = root
            return SimpleNamespace(id="workspace-1")

    assert await chat._confirm_cli_workspace(_Runtime()) == "workspace-1"
    assert prompted["root"] == Path(tmp_path).resolve()
    assert str(tmp_path) in prompted["message"]
    assert [choice.value for choice in prompted["choices"]] == ["current", "later"]


async def test_cli_workspace_confirmation_can_be_deferred(monkeypatch) -> None:
    monkeypatch.setattr(chat.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    class _Prompt:
        async def ask_async(self):
            return "later"

    monkeypatch.setattr(chat.questionary, "select", lambda *_args, **_kwargs: _Prompt())

    class _Runtime:
        async def open_workspace(self, _root):
            raise AssertionError("declining must not register a workspace")

    assert await chat._confirm_cli_workspace(_Runtime()) == ""


async def test_foreground_task_does_not_report_an_empty_model_reply(
    monkeypatch, capsys
) -> None:
    from types import SimpleNamespace

    from Sprout.message.models import OutboundMessage, StreamChunk

    inputs = iter(("帮我写 hello_world.py", "/exit"))

    async def _readline():
        return next(inputs)

    monkeypatch.setattr(chat, "_readline_with_slash_hint", _readline)
    outbound = OutboundMessage(
        content="",
        channel="cli",
        session_id="session-1",
        correlation_id="message-1",
        metadata={
            "task_id": "task-1",
            "foreground_task": True,
            "task_status": "completed",
        },
    )

    class _Metadata:
        async def list_execution_nodes(self, _task_id):
            return []

    class _Runtime:
        storage = SimpleNamespace(metadata=_Metadata())

        async def handle_stream(self, _message):
            yield StreamChunk(outbound=outbound)

        async def get_task(self, _task_id):
            return SimpleNamespace(status=SimpleNamespace(value="completed"))

        async def parked_tasks_for_session(self, _session_id):
            return []

    await chat._repl(
        None,
        session=None,
        user="cli-user",
        model=SimpleNamespace(provider="echo", model="echo-1"),
        runtime=_Runtime(),
        web=SimpleNamespace(),
    )

    output = capsys.readouterr().out
    assert "模型暂时没有返回内容" not in output
    assert "completed" in output


def test_the_exact_scope_note_does_not_promise_a_class(monkeypatch) -> None:
    """Some records have no name to widen to, and must say so.

    The build-tool allowlist and ``git`` are deliberately excluded from
    classing, so the prompt for those has to explain that the choice is
    per-invocation rather than silently offering a class it cannot honour.
    """
    monkeypatch.setenv("SPROUT_CLI_LANG", "en")

    text = _approval_text("exact_scope")

    assert "per-invocation" in text
    assert "class" not in text or "cannot" in text or "no" in text


def test_slash_directory_includes_task_and_status() -> None:
    rows = dict(_slash_rows())
    assert "/task" in rows
    assert "/status" in rows


def test_slash_directory_includes_skill() -> None:
    assert "/skill" in dict(_slash_rows())


def test_skill_subcommands_match_the_cli() -> None:
    """The TUI list must not drift from ``sprout skills`` (one mechanism, not two)."""
    from Sprout.cli.commands.skills import app as skills_app

    declared = {command for command, _ in _skill_subcommands()}
    real = {info.name or info.callback.__name__ for info in skills_app.registered_commands}
    assert declared == real


def test_bare_skill_shows_directory_then_lists_installed(monkeypatch) -> None:
    calls: list[list[str]] = []

    async def _fake(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(chat, "_stream_sprout_command", _fake)
    asyncio.run(chat._handle_skill_command("/skill"))

    assert calls == [["skills", "list"]]


def test_skill_forwards_arguments_to_the_cli(monkeypatch) -> None:
    """``/skill`` must be a thin alias for ``sprout skills``, alias included."""
    calls: list[list[str]] = []

    async def _fake(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(chat, "_stream_sprout_command", _fake)
    asyncio.run(chat._handle_skill_command("/skill search pdf -s url"))
    asyncio.run(chat._handle_skill_command("/skills install https://x/SKILL.md -s url"))

    assert calls == [
        ["skills", "search", "pdf", "-s", "url"],
        ["skills", "install", "https://x/SKILL.md", "-s", "url"],
    ]


def test_skill_subcommands_declare_required_arguments() -> None:
    """Only ``search``/``install`` take a positional; ``list`` takes none."""
    required = _skill_required_args()
    # Commands taking a positional argument must declare it, so a bare
    # ``/skill search`` is caught here rather than in Typer's error panel.
    assert required["search"] and required["find"] and required["install"]
    assert required["list"] is None
    assert required["crawl"] is None
    assert required["index"] is None


def test_skill_missing_required_argument_prints_usage(monkeypatch) -> None:
    """A bare ``/skill search`` must not reach Typer's ``Missing argument`` panel."""
    calls: list[list[str]] = []

    async def _fake(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(chat, "_stream_sprout_command", _fake)
    asyncio.run(chat._handle_skill_command("/skill search"))
    asyncio.run(chat._handle_skill_command("/skill install"))

    assert calls == []


def test_skill_unknown_subcommand_prints_directory(monkeypatch) -> None:
    calls: list[list[str]] = []

    async def _fake(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(chat, "_stream_sprout_command", _fake)
    asyncio.run(chat._handle_skill_command("/skill frobnicate"))

    assert calls == []


def test_skill_subcommand_with_help_is_forwarded(monkeypatch) -> None:
    """``--help`` counts as an argument, so it still reaches the CLI."""
    calls: list[list[str]] = []

    async def _fake(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(chat, "_stream_sprout_command", _fake)
    asyncio.run(chat._handle_skill_command("/skill search --help"))

    assert calls == [["skills", "search", "--help"]]

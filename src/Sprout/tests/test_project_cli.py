"""``sprout project`` read-only surface: every query verb must reach the CLI.

The engine has carried ``symbols`` / ``dependencies`` / ``subgraph`` since the
Workspace Intelligence work, but only ``graph`` and ``knowledge`` were reachable
from the CLI, so part of the query surface existed for tests and the web API
only. These tests pin the CLI commands and their gateway wiring, against a real
runtime whose storage lands in ``tmp_path`` (never in the real sprout home).

They also pin the path contract: graph nodes store an absolute resource path
(the workspace root is resolved on open), while a shell caller types a relative
one, so every path-shaped query has to accept both.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from Sprout.cli.app import app, boot_output_to_stderr
from Sprout.config.loader import load_settings
from Sprout.gateway.project_gateway import ProjectGateway
from Sprout.runtime.factory import create_runtime

SERVICE_PY = '''"""Demo service used by the project CLI tests."""

import os


class RateLimiter:
    """A tiny symbol to find from the CLI."""

    def allow(self) -> bool:
        return True


def helper() -> str:
    return os.sep
'''

APP_PY = '''"""Demo entry point that imports the service module."""

from service import RateLimiter


def main() -> None:
    RateLimiter().allow()
'''


def _sandbox_config(tmp_path: Path) -> Path:
    """A sprout.toml whose every lane is a file under ``tmp_path``."""
    data = tmp_path / "data"
    config = tmp_path / "sprout.toml"
    config.write_text(
        "[storage]\n"
        f'operational = "sqlite:///{(data / "runtime.db").as_posix()}"\n'
        f'knowledge = "sqlite:///{(data / "knowledge.db").as_posix()}"\n'
        f'metadata = "sqlite:///{(data / "sema.db").as_posix()}"\n'
        f'session = "sqlite:///{(data / "session.db").as_posix()}"\n'
        f'blobs_dir = "{(data / "media").as_posix()}"\n'
        f'trajectory_dir = "{(data / "trajectory").as_posix()}"\n'
        "\n"
        "[storage.observations]\n"
        f'dsn = "sqlite:///{(data / "observations.db").as_posix()}"\n'
        "\n"
        "[model]\n"
        'provider = "echo"\n'
        'model = "echo-1"\n'
        "\n"
        # Keep the audit stream inside tmp_path as well: without this the
        # default points at the real ~/.sprout/data/audit/security.jsonl.
        "[security.audit]\n"
        f'path = "{(data / "audit" / "security.jsonl").as_posix()}"\n',
        encoding="utf-8",
    )
    return config


async def _analyzed(tmp_path: Path) -> tuple[ProjectGateway, str]:
    runtime = create_runtime(load_settings(str(_sandbox_config(tmp_path))))
    gateway = ProjectGateway(runtime, transport="cli", default_user="cli-user")
    workspace_root = tmp_path / "demo"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "service.py").write_text(SERVICE_PY, encoding="utf-8")
    (workspace_root / "app.py").write_text(APP_PY, encoding="utf-8")
    opened = await gateway.open_workspace(str(workspace_root))
    await gateway.analyze_workspace(opened.id)
    return gateway, opened.id


# -- the query surface -------------------------------------------------------------


async def test_symbols_lists_classes_and_functions(tmp_path: Path) -> None:
    gateway, workspace_id = await _analyzed(tmp_path)

    nodes = await gateway.query_workspace_symbols(workspace_id)

    kinds = {node.kind for node in nodes}
    assert {"class", "function"} <= kinds
    names = {node.qualified_name or node.name for node in nodes}
    assert any("RateLimiter" in name for name in names)


async def test_symbols_filter_by_kind_and_query(tmp_path: Path) -> None:
    gateway, workspace_id = await _analyzed(tmp_path)

    classes = await gateway.query_workspace_symbols(workspace_id, kind="class")
    assert classes and all(node.kind == "class" for node in classes)

    filtered = await gateway.query_workspace_symbols(workspace_id, query="RateLimiter")
    assert filtered
    assert all(
        "ratelimiter" in (node.qualified_name or node.name).casefold() for node in filtered
    )


@pytest.mark.parametrize("spelling", ["relative", "absolute"])
async def test_dependencies_walks_out_of_a_file(tmp_path: Path, spelling: str) -> None:
    """The shell-typed relative path and the stored absolute path both resolve."""
    gateway, workspace_id = await _analyzed(tmp_path)
    path = "app.py"
    if spelling == "absolute":
        path = (tmp_path / "demo" / "app.py").as_posix()

    result = await gateway.query_workspace_dependencies(workspace_id, path)

    assert result.edges, "app.py imports service.py, so it must have an outgoing edge"
    assert any(edge.relation == "imports" for edge in result.edges)
    touched = {edge.source for edge in result.edges} | {edge.target for edge in result.edges}
    assert touched <= {node.id for node in result.nodes}


async def test_dependencies_walks_back_to_the_importer(tmp_path: Path) -> None:
    gateway, workspace_id = await _analyzed(tmp_path)

    result = await gateway.query_workspace_dependencies(
        workspace_id, "service.py", direction="in"
    )

    assert result.edges
    assert any(edge.relation == "imports" for edge in result.edges)
    targets = {edge.target for edge in result.edges}
    assert targets <= {node.id for node in result.nodes}


async def test_dependencies_returns_nothing_for_an_unknown_path(tmp_path: Path) -> None:
    """A near miss must not be fuzzy-matched onto a real file."""
    gateway, workspace_id = await _analyzed(tmp_path)

    result = await gateway.query_workspace_dependencies(workspace_id, "missing.py")

    assert result.nodes == () and result.edges == ()


async def test_subgraph_returns_the_neighbourhood(tmp_path: Path) -> None:
    gateway, workspace_id = await _analyzed(tmp_path)

    result = await gateway.query_workspace_subgraph(workspace_id, "RateLimiter", max_depth=2)

    assert result.nodes and result.edges
    assert any("RateLimiter" in (node.qualified_name or node.name) for node in result.nodes)


async def test_subgraph_accepts_a_file_path_as_the_seed(tmp_path: Path) -> None:
    """File nodes are named by absolute path; a relative seed must still work."""
    gateway, workspace_id = await _analyzed(tmp_path)

    result = await gateway.query_workspace_subgraph(workspace_id, "service.py")

    assert result.nodes and result.edges
    assert any(
        node.resource is not None and node.resource.path.endswith("service.py")
        for node in result.nodes
    )


async def test_missing_node_yields_an_empty_subgraph(tmp_path: Path) -> None:
    gateway, workspace_id = await _analyzed(tmp_path)

    result = await gateway.query_workspace_subgraph(workspace_id, "NoSuchSymbol")

    assert result.nodes == () and result.edges == ()


# -- the CLI commands -------------------------------------------------------------


def test_project_help_lists_every_query_command() -> None:
    result = CliRunner().invoke(app, ["project", "--help"])

    assert result.exit_code == 0
    for name in ("workspaces", "symbols", "dependencies", "subgraph"):
        assert name in result.stdout


def test_query_commands_document_their_json_mode() -> None:
    """Every new query command promises a scriptable payload."""
    for name in ("symbols", "dependencies", "subgraph", "workspaces"):
        result = CliRunner().invoke(app, ["project", name, "--help"])
        assert result.exit_code == 0, name
        assert "--json" in result.stdout, name


def test_sprout_help_advertises_the_project_flow() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "sprout run" in result.stdout
    assert "sprout project analyze" in result.stdout
    assert "sprout project dependencies" in result.stdout


def test_run_command_is_a_top_level_project_loop() -> None:
    result = CliRunner().invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "project" in result.stdout.casefold()
    assert "strategy" in result.stdout.casefold()
    assert "validation" in result.stdout.casefold()


def test_run_manifest_brief_renders_scan_facts() -> None:
    from Sprout.cli.commands.run import _manifest_brief
    from Sprout.workspace.models import WorkspaceManifest

    manifest = WorkspaceManifest(
        workspace_id="ws-1",
        detected_languages=("python", "typescript"),
        framework_hints=("fastapi",),
        test_commands=("pytest -q",),
    )

    brief = _manifest_brief(manifest)
    assert "languages=python,typescript" in brief
    assert "frameworks=fastapi" in brief
    assert "test=pytest -q" in brief


def test_run_clean_instruction_strips_markup() -> None:
    from Sprout.cli.commands.run import _clean_instruction

    assert _clean_instruction("```\nFix the flaky auth test\n```") == (
        "Fix the flaky auth test"
    )
    assert _clean_instruction('"Add retries to the queue worker"') == (
        "Add retries to the queue worker"
    )
    assert _clean_instruction("Instruction: Remove dead code") == "Remove dead code"


@pytest.mark.asyncio
async def test_run_resolve_approvals_approves_pending_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from Sprout.cli.commands import run as run_module
    from Sprout.execution.models import ChangeProposalStatus
    from Sprout.task.models import TaskStatus

    decisions: list[tuple[str, bool]] = []
    state = {"approved": False}
    monkeypatch.setattr(
        run_module,
        "_ask_approval",
        lambda message, **_kwargs: "approve",
    )

    class _Proposal:
        id = "proposal-1"
        status = ChangeProposalStatus.PENDING
        files_changed = ("a.py", "b.py")
        metadata = {"summary": "add retries"}

    class _Runtime:
        async def pending_approvals(self) -> list:
            return []

        async def list_change_proposals(self, task_id: str) -> list:
            return [_Proposal()]

        async def approve_change_proposal(self, proposal_id: str, decided_by: str) -> None:
            decisions.append((proposal_id, True))
            state["approved"] = True

        async def get_task(self, task_id: str):
            status = TaskStatus.COMPLETED if state["approved"] else TaskStatus.WAITING_APPROVAL
            return SimpleNamespace(id=task_id, status=status)

    task = SimpleNamespace(id="task-1", status=TaskStatus.WAITING_APPROVAL)
    result, quit_loop = await run_module._resolve_approvals(_Runtime(), task)

    assert decisions == [("proposal-1", True)]
    assert quit_loop is False
    assert result.status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_resolve_approvals_decides_verification_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from Sprout.cli.commands import run as run_module
    from Sprout.task.models import TaskStatus

    decisions: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        run_module,
        "_ask_approval",
        lambda message, **_kwargs: "approve",
    )

    class _Record:
        id = "grant-1"
        task_id = "task-1"
        tool = "process_run"
        action_summary = '{"command": "pytest -q"}'
        action_hash = "h"

    class _Runtime:
        async def pending_approvals(self) -> list:
            return [_Record()]

        async def decide_approval(
            self, approval_id: str, approved: bool, *, decided_by: str
        ) -> None:
            decisions.append((approval_id, approved))

        async def list_change_proposals(self, task_id: str) -> list:
            return []

        async def get_task(self, task_id: str):
            return SimpleNamespace(id=task_id, status=TaskStatus.COMPLETED)

    task = SimpleNamespace(id="task-1", status=TaskStatus.WAITING_APPROVAL)
    _, quit_loop = await run_module._resolve_approvals(_Runtime(), task)

    assert decisions == [("grant-1", True)]
    assert quit_loop is False


@pytest.mark.asyncio
async def test_run_derive_next_instruction_uses_configured_model() -> None:
    from types import SimpleNamespace

    from Sprout.cli.commands.run import _derive_next_instruction
    from Sprout.llm.messages import LLMMessage, LLMResponse
    from Sprout.workspace.models import WorkspaceManifest

    class _Model:
        async def chat(self, messages: list[LLMMessage]):
            assert any(
                message.content and "Project scan" in message.content
                for message in messages
            )
            return LLMResponse(content="Task: tighten the retry backoff")

    class _Registry:
        default_name = "real"

        def default(self):
            return _Model()

    class _Runtime:
        models = _Registry()

        async def scan_workspace(self, workspace_id: str) -> WorkspaceManifest:
            return WorkspaceManifest(workspace_id=workspace_id, detected_languages=("python",))

    instruction = await _derive_next_instruction(
        _Runtime(), SimpleNamespace(id="ws-1"), "add retries"
    )

    assert instruction == "tighten the retry backoff"


@pytest.mark.asyncio
async def test_run_derive_next_instruction_falls_back_offline() -> None:
    from types import SimpleNamespace

    from Sprout.cli.commands.run import _derive_next_instruction

    class _Registry:
        default_name = "echo"

    class _Runtime:
        models = _Registry()

    assert (
        await _derive_next_instruction(_Runtime(), SimpleNamespace(id="ws-1"), "")
        is None
    )


@pytest.mark.asyncio
async def test_run_whole_project_verify_reports_outcomes() -> None:
    from types import SimpleNamespace

    from Sprout.cli.commands.run import _whole_project_verify
    from Sprout.execution.models import ProcessResult
    from Sprout.workspace.models import WorkspaceManifest

    class _Runtime:
        async def scan_workspace(self, workspace_id: str) -> WorkspaceManifest:
            return WorkspaceManifest(
                workspace_id=workspace_id, test_commands=("pytest -q",)
            )

        async def run_task_process(self, task_id: str, command: tuple[str, ...]):
            return ProcessResult(command=command, exit_code=0, allowed=True)

    outcomes = await _whole_project_verify(
        _Runtime(), SimpleNamespace(id="task-1", workspace_id="ws-1")
    )

    assert outcomes == [
        {
            "command": "pytest -q",
            "passed": True,
            "withheld": False,
        }
    ]


# -- stdout hygiene -----------------------------------------------------------------


def test_boot_announcements_are_routed_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    with boot_output_to_stderr():
        print("Sprout 主目录已就绪")  # what ensure_sprout_home() prints

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Sprout 主目录已就绪" in captured.err


def test_main_keeps_the_boot_hooks_inside_the_redirect() -> None:
    """Structural guard: a dropped ``with`` would silently poison ``--json`` again."""
    module = importlib.import_module("Sprout.cli.app")
    source = Path(module.__file__).read_text(encoding="utf-8")
    body = source.split("def main() -> None:", 1)[1]
    redirect_at = body.index("boot_output_to_stderr()")

    for call in ("load_env_file()", "ensure_sprout_home()"):
        assert body.index(call) > redirect_at, f"{call} must run inside the redirect"

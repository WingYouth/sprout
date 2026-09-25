"""Tests for the sandbox read/edit/write tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from Sprout.execution.file_broker import FileBroker
from Sprout.execution.models import SandboxRef
from Sprout.execution.sandbox_tool import (
    SandboxApplyPatchTool,
    SandboxEditTool,
    SandboxListTool,
    SandboxReadTool,
    SandboxSearchTool,
)
from Sprout.security.engine import PolicyEngine


def _sandbox(root: Path) -> SandboxRef:
    return SandboxRef(id="sb", kind="git_worktree", root=root)


def test_sandbox_read_tool_returns_full_content(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    tool = SandboxReadTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(tool.invoke({"path": "a.py"}))

    assert result.ok is True
    assert result.content == "line1\nline2\nline3\n"


def test_sandbox_edit_tool_replaces_unique_text(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    tool = SandboxEditTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "path": "a.py",
                "old_text": "    return 1",
                "new_text": "    return 2",
            }
        )
    )

    assert result.ok is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == (
        "def foo():\n    return 2\n"
    )


def test_sandbox_edit_tool_rejects_non_unique_text(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = 1\n", encoding="utf-8")
    tool = SandboxEditTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke({"path": "a.py", "old_text": "1", "new_text": "2"})
    )

    assert result.ok is False
    assert "2 times" in (result.error or "")


def test_sandbox_apply_patch_tool_updates_existing_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "patch": (
                    "--- a/a.py\n"
                    "+++ b/a.py\n"
                    "@@ -1,2 +1,2 @@\n"
                    " def foo():\n"
                    "-    return 1\n"
                    "+    return 2\n"
                )
            }
        )
    )

    assert result.ok is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == (
        "def foo():\n    return 2\n"
    )


def test_sandbox_apply_patch_tool_creates_new_file(tmp_path: Path) -> None:
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "patch": (
                    "--- /dev/null\n"
                    "+++ b/new.py\n"
                    "@@ -0,0 +1,1 @@\n"
                    "+print('hi')\n"
                )
            }
        )
    )

    assert result.ok is True
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_sandbox_apply_patch_tool_rejects_missing_non_new_file(
    tmp_path: Path,
) -> None:
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "patch": (
                    "--- a/missing.py\n"
                    "+++ b/missing.py\n"
                    "@@ -1,1 +1,1 @@\n"
                    "-old\n"
                    "+new\n"
                )
            }
        )
    )

    assert result.ok is False
    assert "missing file" in (result.error or "")


def test_sandbox_list_tool_lists_nested_files_without_git(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    tool = SandboxListTool(_sandbox(tmp_path))

    result = asyncio.run(tool.invoke({"include": "*.py"}))

    assert result.ok is True
    assert result.content == "src/app.py"


def test_sandbox_search_tool_returns_path_line_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    tool = SandboxSearchTool(_sandbox(tmp_path))

    result = asyncio.run(tool.invoke({"query": "return"}))

    assert result.ok is True
    assert result.content == "a.py:2:    return 1"


def test_sandbox_read_tool_supports_offset_and_limit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    tool = SandboxReadTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke({"path": "a.py", "offset": 1, "limit": 1})
    )

    assert result.ok is True
    assert result.content == "2: two"


def test_sandbox_apply_patch_tool_deletes_a_file(tmp_path: Path) -> None:
    (tmp_path / "gone.py").write_text("print('bye')\n", encoding="utf-8")
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "patch": (
                    "--- a/gone.py\n"
                    "+++ /dev/null\n"
                    "@@ -1,1 +0,0 @@\n"
                    "-print('bye')\n"
                )
            }
        )
    )

    assert result.ok is True
    assert not (tmp_path / "gone.py").exists()


def test_sandbox_apply_patch_tool_renames_a_file(tmp_path: Path) -> None:
    (tmp_path / "old.py").write_text("print('hi')\n", encoding="utf-8")
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke(
            {
                "patch": (
                    "diff --git a/old.py b/new.py\n"
                    "similarity index 100%\n"
                    "rename from old.py\n"
                    "rename to new.py\n"
                )
            }
        )
    )

    assert result.ok is True
    assert not (tmp_path / "old.py").exists()
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_sandbox_apply_patch_tool_rejects_binary_patches(tmp_path: Path) -> None:
    tool = SandboxApplyPatchTool(_sandbox(tmp_path), FileBroker(PolicyEngine()))

    result = asyncio.run(
        tool.invoke({"patch": "GIT binary patch\nliteral 0\n"})
    )

    assert result.ok is False
    assert "Binary patches are not supported" in (result.error or "")

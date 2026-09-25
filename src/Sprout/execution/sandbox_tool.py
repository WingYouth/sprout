"""Agent-visible sandbox file tools.

These are the only tools an execution node can call: they are scoped to one
``SandboxRef`` and never shell out for file discovery, so an agent cannot
escape its worktree by passing a clever ``path`` argument.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from Sprout.execution.file_broker import FileBroker
from Sprout.execution.git_env import git_args, git_env
from Sprout.execution.models import SandboxRef
from Sprout.execution.patch import PatchError, apply_patch_to_text, parse_patch
from Sprout.execution.proc import run_capture
from Sprout.task.models import DelegationScope
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec

_MAX_SEARCH_BYTES = 512 * 1024
_MAX_SEARCH_RESULTS = 200
_MAX_LIST_ENTRIES = 500


def _sandbox_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_sandbox_files(root: Path, include: str) -> list[tuple[str, Path]]:
    """Walk the sandbox root without following symlinks or entering ``.git``."""
    found: list[tuple[str, Path]] = []
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root_resolved):
        dirnames[:] = [
            name
            for name in dirnames
            if name != ".git" and not os.path.islink(os.path.join(dirpath, name))
        ]
        for name in filenames:
            full = Path(os.path.join(dirpath, name))
            if os.path.islink(full):
                continue
            relative = full.relative_to(root_resolved).as_posix()
            if include != "*" and not fnmatch.fnmatch(relative, include):
                continue
            found.append((relative, full))
    found.sort(key=lambda item: item[0])
    return found


class SandboxWriteTool:
    """Lets an agent write files into its current sandbox worktree."""

    def __init__(
        self,
        sandbox: SandboxRef,
        broker: FileBroker,
        *,
        scope: DelegationScope | None = None,
        task_id: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._broker = broker
        #: The owning task's scope, so a channel that granted read-only access
        #: cannot obtain a sandbox write through the agent's tool path.
        self._scope = scope
        self._task_id = task_id
        self.spec = ToolSpec(
            name="sandbox_write_file",
            description=(
                "Write a UTF-8 text file inside the current sandbox worktree, "
                "creating it (and any missing parent directories) if it does not "
                "exist, or replacing it entirely if it does. Use this to create "
                "new files; use sandbox_edit_file to change part of an existing one."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Sandbox-relative file path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full UTF-8 file content.",
                    },
                },
                "required": ["path", "content"],
            },
            risk_level="medium",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(path, str) or not path.strip():
            return ToolResult.failure("Argument 'path' must be a non-empty string")
        if not isinstance(content, str):
            return ToolResult.failure("Argument 'content' must be a string")

        result = await self._broker.write_text(
            self._sandbox, path, content, task_id=self._task_id, scope=self._scope
        )
        if not result.wrote:
            return ToolResult.failure(result.reason or "Sandbox write failed")
        return ToolResult.success(f"Wrote {path}", data={"path": path})


class SandboxDeleteTool:
    """Delete one file from the sandbox; the project remains unchanged until apply."""

    def __init__(
        self,
        sandbox: SandboxRef,
        broker: FileBroker,
        *,
        scope: DelegationScope | None = None,
        task_id: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._broker = broker
        self._scope = scope
        self._task_id = task_id
        self.spec = ToolSpec(
            name="sandbox_delete_file",
            description=(
                "Delete one file inside the current sandbox worktree. This does not "
                "delete the project copy; the deletion appears in the review diff "
                "and reaches the project only after the normal apply approval."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Sandbox-relative path of the file to delete.",
                    }
                },
                "required": ["path"],
            },
            # The mutation stays in the task worktree. The project's existing
            # change-proposal approval is the single human gate before apply.
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return ToolResult.failure("Argument 'path' must be a non-empty string")
        if not await self._broker.exists(
            self._sandbox, path, task_id=self._task_id, scope=self._scope
        ):
            return ToolResult.failure(
                f"Delete target does not exist inside the sandbox: {path!r}"
            )
        result = await self._broker.delete(
            self._sandbox, path, task_id=self._task_id, scope=self._scope
        )
        if not result.wrote:
            return ToolResult.failure(result.reason or f"Could not delete {path}")
        return ToolResult.success(
            f"Deleted {path} from the sandbox; the deletion is pending project approval.",
            data={"path": path, "deleted": True},
        )


class SandboxReadTool:
    """Lets an agent read the full text of a file in its sandbox worktree.

    Registered on two paths, and the description has to be true of both. A task
    node points it at a ``git_worktree`` sandbox; the conversation path points
    the *same class* at the working directory. Naming the worktree in the
    description therefore read as "this tool needs a sandbox", so an agent asked
    to read an ordinary file concluded it had no reader available and said so —
    the tool was in its list the whole time. The description is now built from
    the root actually in hand.
    """

    def __init__(
        self,
        sandbox: SandboxRef,
        broker: FileBroker,
        *,
        scope: DelegationScope | None = None,
        task_id: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._broker = broker
        self._scope = scope
        self._task_id = task_id
        self.spec = ToolSpec(
            name="sandbox_read_file",
            description=self._describe(sandbox),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path, relative to the readable root.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Zero-based first line to return.",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to return; 0 means all.",
                        "default": 0,
                    },
                },
                "required": ["path"],
            },
            risk_level="low",
        )

    @staticmethod
    def _describe(sandbox: SandboxRef) -> str:
        """Describe the file source in terms of what it actually is.

        A worktree reads as a sandbox; anything else (the conversation path's
        working directory) reads as the project. Saying "sandbox worktree" for
        both is what made an agent told to read a file reply that it had no
        tool for reading — true of the wording, false of the tool.
        """
        if getattr(sandbox, "kind", "") == "git_worktree":
            return (
                "Read the full UTF-8 text of a file in the task's sandbox "
                "worktree, given its path relative to the worktree root."
            )
        return (
            "Read the full UTF-8 text of a file from the workspace, given its "
            "path relative to the workspace root. Use this to inspect source "
            "code, configuration, or documentation."
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return ToolResult.failure("Argument 'path' must be a non-empty string")
        offset = _bounded_int(
            arguments.get("offset"), default=0, minimum=0, maximum=1_000_000
        )
        limit = _bounded_int(
            arguments.get("limit"), default=0, minimum=0, maximum=1_000_000
        )

        result = await self._broker.read_text(
            self._sandbox, path, task_id=self._task_id, scope=self._scope
        )
        if not result.wrote:
            return ToolResult.failure(result.reason or "Sandbox read failed")
        if offset or limit:
            lines = result.content.splitlines()
            lines = lines[offset : offset + limit if limit else None]
            numbered = "\n".join(
                f"{offset + index + 1}: {line}"
                for index, line in enumerate(lines)
            )
            return ToolResult.success(
                numbered,
                data={
                    "path": path,
                    "offset": offset,
                    "limit": limit,
                    "total_lines": len(result.content.splitlines()),
                },
            )
        return ToolResult.success(result.content, data={"path": path})


class SandboxEditTool:
    """Lets an agent apply a precise text replacement instead of rewriting a file."""

    def __init__(
        self,
        sandbox: SandboxRef,
        broker: FileBroker,
        *,
        scope: DelegationScope | None = None,
        task_id: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._broker = broker
        self._scope = scope
        self._task_id = task_id
        self.spec = ToolSpec(
            name="sandbox_edit_file",
            description=(
                "Replace one exact text block in a sandbox file with new text. "
                "The old_text must appear exactly once."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Sandbox-relative file path.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact existing text to replace.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
            risk_level="medium",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        path = arguments.get("path")
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        if not isinstance(path, str) or not path.strip():
            return ToolResult.failure("Argument 'path' must be a non-empty string")
        if not isinstance(old_text, str) or not old_text:
            return ToolResult.failure("Argument 'old_text' must be a non-empty string")
        if not isinstance(new_text, str):
            return ToolResult.failure("Argument 'new_text' must be a string")

        read = await self._broker.read_text(
            self._sandbox, path, task_id=self._task_id, scope=self._scope
        )
        if not read.wrote:
            return ToolResult.failure(read.reason or "Sandbox read failed")

        occurrences = read.content.count(old_text)
        if occurrences == 0:
            return ToolResult.failure(
                "old_text was not found in the file; read the file first and retry"
            )
        if occurrences > 1:
            return ToolResult.failure(
                f"old_text appears {occurrences} times; make it unique and retry"
            )

        updated = read.content.replace(old_text, new_text, 1)
        result = await self._broker.write_text(
            self._sandbox, path, updated, task_id=self._task_id, scope=self._scope
        )
        if not result.wrote:
            return ToolResult.failure(result.reason or "Sandbox write failed")
        return ToolResult.success(f"Edited {path}", data={"path": path})


class SandboxApplyPatchTool:
    """Applies a unified diff across one or more sandbox files."""

    def __init__(
        self,
        sandbox: SandboxRef,
        broker: FileBroker,
        *,
        scope: DelegationScope | None = None,
        task_id: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._broker = broker
        self._scope = scope
        self._task_id = task_id
        self.spec = ToolSpec(
            name="sandbox_apply_patch",
            description=(
                "Apply a unified diff (git diff / diff -u) to files inside the "
                "current sandbox worktree. Supports multiple hunks and multiple "
                "files, and can create, delete, or rename files."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": (
                            "Complete unified diff text, including ---/+++ file "
                            "headers and @@ hunk headers."
                        ),
                    },
                },
                "required": ["patch"],
            },
            risk_level="medium",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        patch = arguments.get("patch")
        if not isinstance(patch, str) or not patch.strip():
            return ToolResult.failure("Argument 'patch' must be a non-empty string")

        if "GIT binary patch" in patch or "Binary files " in patch:
            return ToolResult.failure(
                "Binary patches are not supported; edit text files only"
            )

        try:
            file_patches = parse_patch(patch)
        except PatchError as exc:
            return ToolResult.failure(f"Invalid patch: {exc}")

        touched: list[str] = []
        for file_patch in file_patches:
            path = file_patch.path.strip()
            if not path:
                return ToolResult.failure(
                    "Patch contains an empty target path"
                )

            if file_patch.rename_from:
                rename_from = file_patch.rename_from.strip()
                if not rename_from:
                    return ToolResult.failure("Patch contains an empty rename source")
                if not await self._broker.exists(
                    self._sandbox,
                    rename_from,
                    task_id=self._task_id,
                    scope=self._scope,
                ):
                    return ToolResult.failure(
                        f"Rename source does not exist: {rename_from!r}"
                    )
                if await self._broker.exists(
                    self._sandbox,
                    path,
                    task_id=self._task_id,
                    scope=self._scope,
                ):
                    return ToolResult.failure(
                        f"Rename target already exists: {path!r}"
                    )
                read = await self._broker.read_text(
                    self._sandbox,
                    rename_from,
                    task_id=self._task_id,
                    scope=self._scope,
                )
                if not read.wrote:
                    return ToolResult.failure(read.reason or f"Could not read {rename_from}")
                write = await self._broker.write_text(
                    self._sandbox,
                    path,
                    read.content,
                    task_id=self._task_id,
                    scope=self._scope,
                )
                if not write.wrote:
                    return ToolResult.failure(write.reason or f"Could not write {path}")
                deleted = await self._broker.delete(
                    self._sandbox,
                    rename_from,
                    task_id=self._task_id,
                    scope=self._scope,
                )
                if not deleted.wrote:
                    return ToolResult.failure(
                        deleted.reason or f"Could not delete {rename_from}"
                    )
                touched.append(f"{rename_from} -> {path}")
                continue

            if file_patch.is_delete:
                if not await self._broker.exists(
                    self._sandbox,
                    path,
                    task_id=self._task_id,
                    scope=self._scope,
                ):
                    return ToolResult.failure(f"Delete target does not exist: {path!r}")
                deleted = await self._broker.delete(
                    self._sandbox,
                    path,
                    task_id=self._task_id,
                    scope=self._scope,
                )
                if not deleted.wrote:
                    return ToolResult.failure(
                        deleted.reason or f"Could not delete {path}"
                    )
                touched.append(path)
                continue

            exists = await self._broker.exists(
                self._sandbox,
                path,
                task_id=self._task_id,
                scope=self._scope,
            )
            is_new_file = all(
                hunk.old_start == 0 and hunk.old_count == 0
                for hunk in file_patch.hunks
            )
            if not exists:
                if not is_new_file:
                    return ToolResult.failure(
                        f"Patch targets missing file {path!r}; only new-file "
                        "patches (old line 0) can create files"
                    )
                current = ""
            else:
                read = await self._broker.read_text(
                    self._sandbox,
                    path,
                    task_id=self._task_id,
                    scope=self._scope,
                )
                if not read.wrote:
                    return ToolResult.failure(read.reason or f"Could not read {path}")
                current = read.content

            try:
                updated = apply_patch_to_text(current, file_patch)
            except PatchError as exc:
                return ToolResult.failure(f"Patch failed for {path}: {exc}")

            write = await self._broker.write_text(
                self._sandbox,
                path,
                updated,
                task_id=self._task_id,
                scope=self._scope,
            )
            if not write.wrote:
                return ToolResult.failure(write.reason or f"Could not write {path}")
            touched.append(path)

        return ToolResult.success(
            f"Applied patch to {len(touched)} file(s)",
            data={"paths": touched},
        )


class SandboxListTool:
    """List text-visible files inside the sandbox worktree."""

    def __init__(self, sandbox: SandboxRef) -> None:
        self._sandbox = sandbox
        self.spec = ToolSpec(
            name="sandbox_list_files",
            description=(
                "List files inside the current sandbox worktree, optionally "
                "filtered by a glob such as '*.py' or 'src/**'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "include": {
                        "type": "string",
                        "description": "Optional glob pattern for relative paths.",
                        "default": "*",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": "Maximum number of paths to return.",
                        "default": 200,
                    },
                },
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        include = arguments.get("include") or "*"
        if not isinstance(include, str) or not include.strip():
            include = "*"
        max_entries = _bounded_int(
            arguments.get("max_entries"), default=200, minimum=1, maximum=500
        )
        files = _iter_sandbox_files(self._sandbox.root, include)
        if not files:
            return ToolResult.success("(no files matched)")
        paths = [relative for relative, _ in files[:_MAX_LIST_ENTRIES][:max_entries]]
        return ToolResult.success(
            "\n".join(paths),
            data={"paths": paths, "truncated": len(files) > len(paths)},
        )


class SandboxSearchTool:
    """Search text files inside the sandbox worktree."""

    def __init__(self, sandbox: SandboxRef) -> None:
        self._sandbox = sandbox
        self.spec = ToolSpec(
            name="sandbox_search",
            description=(
                "Search text files inside the current sandbox worktree for a "
                "substring or regular expression and return path:line matches."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text or regular expression to search for.",
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "Treat query as a regular expression.",
                        "default": False,
                    },
                    "include": {
                        "type": "string",
                        "description": "Optional glob such as '*.py'.",
                        "default": "*",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return.",
                        "default": 100,
                    },
                },
                "required": ["query"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            return ToolResult.failure("Argument 'query' must be a non-empty string")
        include = arguments.get("include") or "*"
        if not isinstance(include, str) or not include.strip():
            include = "*"
        max_results = _bounded_int(
            arguments.get("max_results"), default=100, minimum=1, maximum=500
        )
        regex = bool(arguments.get("regex"))
        try:
            pattern = re.compile(query) if regex else re.compile(re.escape(query))
        except re.error as exc:
            return ToolResult.failure(f"Invalid search pattern: {exc}")

        matches: list[str] = []
        truncated = False
        for relative, full in _iter_sandbox_files(self._sandbox.root, include):
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size > _MAX_SEARCH_BYTES:
                continue
            try:
                data = full.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:4096]:
                continue
            text = data.decode("utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{relative}:{line_no}:{line}")
                    if len(matches) >= _MAX_SEARCH_RESULTS:
                        truncated = True
                        break
            if truncated or len(matches) >= max_results:
                break
        result = matches[:max_results]
        if not result:
            return ToolResult.success("(no matches found)")
        return ToolResult.success(
            "\n".join(result),
            data={"matches": result, "truncated": truncated or len(matches) > len(result)},
        )


class SandboxGitTool:
    """Read-only git views scoped to the sandbox worktree."""

    _OPERATIONS = {"status", "diff", "log"}

    def __init__(self, sandbox: SandboxRef) -> None:
        self._sandbox = sandbox
        self.spec = ToolSpec(
            name="sandbox_git_inspect",
            description=(
                "Read-only git views of the sandbox worktree: status, diff, "
                "or recent log."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": sorted(self._OPERATIONS),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum log entries.",
                        "default": 20,
                    },
                },
                "required": ["operation"],
            },
            risk_level="low",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        operation = arguments.get("operation")
        if operation not in self._OPERATIONS:
            return ToolResult.failure(
                f"Invalid operation; expected one of: {', '.join(sorted(self._OPERATIONS))}"
            )
        if operation == "status":
            args = ("status", "--porcelain=v1", "--untracked-files=all")
        elif operation == "diff":
            args = ("diff", "--no-color", "--no-ext-diff")
        else:
            limit = _bounded_int(arguments.get("limit"), default=20, minimum=1, maximum=100)
            args = ("log", "--oneline", "-n", str(limit))

        code, stdout, stderr = await run_capture(
            "git",
            *git_args("-C", str(self._sandbox.root), *args),
            env=git_env(),
            timeout=30.0,
        )
        if code != 0:
            return ToolResult.failure(stderr.strip() or f"git {operation} failed")
        return ToolResult.success(stdout.strip() or "(empty)")


def _bounded_int(
    value: Any, *, default: int, minimum: int, maximum: int
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))

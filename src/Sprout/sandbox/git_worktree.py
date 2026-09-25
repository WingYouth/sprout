"""Git worktree-backed sandbox provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

from Sprout.execution.git_env import git_args, git_env
from Sprout.execution.models import DiffResult, SandboxRef
from Sprout.execution.proc import run_capture
from Sprout.security.secret_broker import SecretBroker
from Sprout.workspace.models import Workspace

# Untrusted code run in the sandbox must be bounded: without a deadline a
# runaway script (``while True``) would hold the worktree forever. Git plumbing
# is trusted and deliberately unbounded so a slow clone is never killed.
_DEFAULT_CODE_TIMEOUT = 60.0

#: Pathspecs excluded from the change set, in git's ``:(exclude,glob)`` magic.
#:
#: Verification runs *inside* the sandbox, so it writes bytecode caches, pytest
#: state, and ruff caches right next to the agent's edits. Git reports all of it
#: as untracked changes, and the raw status view therefore offered to commit the
#: caches as if the agent had written them. A repository that ignores them
#: (``.gitignore``) hid the problem; one that does not — the common case, and
#: the one a task is most likely to be pointed at — did not.
#:
#: These are *derived* artifacts: they are a function of the source, so nothing
#: is lost by excluding them, and they are never something an approver should
#: have to read. ``*.py[cod]`` catches the ``.pyo``/``.pyd`` variants too, and
#: the ``**/`` prefix matches at every depth including the repository root.
#:
#: Deliberately *not* a ``.gitignore`` write and deliberately not every entry of
#: the scanner's exclude list: the harness must not edit the repository it is
#: proposing changes to, and a genuine source edit that happens to sit in
#: ``build/`` or ``dist/`` is still a change the approver should see.
_SANDBOX_EXCLUDES = (
    ":(exclude,glob)**/__pycache__/**",
    ":(exclude,glob)**/*.py[cod]",
    ":(exclude,glob)**/.pytest_cache/**",
    ":(exclude,glob)**/.ruff_cache/**",
    ":(exclude,glob)**/.mypy_cache/**",
)


class GitWorktreeSandbox:
    """Creates isolated Git worktrees for project mutations."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def create(self, *, branch: str | None = None) -> SandboxRef:
        if not (self._workspace.root / ".git").exists():
            raise ValueError(f"Workspace is not a Git repository: {self._workspace.root}")
        branch_name = branch or f"sprout-sandbox-{uuid4().hex[:8]}"
        sandbox_root = self._workspace.root.parent / f".sprout-{branch_name}"
        await self._run(
            "git",
            "-C",
            str(self._workspace.root),
            "worktree",
            "add",
            "-b",
            branch_name,
            str(sandbox_root),
        )
        return SandboxRef(
            id=str(uuid4()),
            kind="git_worktree",
            root=sandbox_root,
            worktree_ref=branch_name,
        )

    async def diff(self, ref: SandboxRef) -> DiffResult:
        # ``git diff`` only shows tracked changes. The agent writes new files
        # without staging them, so record intent-to-add first; that makes
        # untracked files appear in the diff as new-file hunks.
        # Excluded here too: intent-to-add on a bytecode cache would put it in
        # the index only to be filtered back out of the diff, and the index is
        # left behind in the worktree for whoever inspects it next.
        await self._run(
            "git",
            "-C",
            str(ref.root),
            "add",
            "-N",
            "--",
            ".",
            *_SANDBOX_EXCLUDES,
        )
        output = await self._run(
            "git",
            "-C",
            str(ref.root),
            "diff",
            "--no-color",
            # A repository may point ``diff.external`` at a program of its
            # choosing; the diff is data here, never a command to run.
            "--no-ext-diff",
            # ``--`` ends the revision list; everything after it is a pathspec,
            # so the excludes below cannot be read as a revision name.
            "--",
            ".",
            *_SANDBOX_EXCLUDES,
        )
        return DiffResult(path="workspace", diff_text=output)

    async def changed_files(self, ref: SandboxRef) -> tuple[str, ...]:
        """Workspace-relative paths the task touched inside the sandbox.

        ``git diff --name-only`` only lists *tracked* files, but the agent writes
        new files into the worktree without staging them, so the status view is
        what actually covers the change set. ``core.quotepath=false`` keeps
        non-ASCII paths readable instead of C-style escaped.

        The verification step runs in this same worktree, so its caches are
        filtered out here — see :data:`_SANDBOX_EXCLUDES`. Without that, the
        change set described work the agent never did.
        """
        output = await self._run(
            "git",
            "-c",
            "core.quotepath=false",
            "-C",
            str(ref.root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            ".",
            *_SANDBOX_EXCLUDES,
        )
        paths: list[str] = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            entry = line[3:].strip().strip('"')
            if not entry:
                continue
            # Renames are reported as "old -> new"; the new name is the result.
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1].strip().strip('"')
            if entry not in paths:
                paths.append(entry)
        return tuple(paths)

    async def run_code(
        self,
        ref: SandboxRef,
        language: str,
        code: str,
        *,
        args: tuple[str, ...] = (),
    ) -> str:
        """Run code in the isolated worktree using a language runtime.

        The child gets the whitelisted environment, not the parent's. This is
        the only path that runs *untrusted* code — model-authored, possibly
        influenced by a fetched skill or repository contents — and inheriting
        the parent environment handed it every declared secret (``DEEPSEEK_API_KEY``
        and friends) for free. Every other spawn point already whitelists:
        ``ProcessBroker`` and ``CliRunTool`` via ``SecretBroker.child_env``, and
        the git helpers via ``git_env``.
        """
        executable, base_args = _language_command(language, code)
        exit_code, stdout, stderr = await run_capture(
            executable,
            *base_args,
            *args,
            cwd=ref.root,
            env=SecretBroker().child_env(base_env=os.environ),
            timeout=_DEFAULT_CODE_TIMEOUT,
        )
        if exit_code != 0:
            detail = stderr.strip()
            raise RuntimeError(detail or f"{language} exited with code {exit_code}")
        return stdout

    async def remove(self, ref: SandboxRef) -> None:
        self._ensure_safe_root(ref)

        if Path(ref.root).exists():
            try:
                await self._run(
                    "git",
                    "-C",
                    str(self._workspace.root),
                    "worktree",
                    "remove",
                    "--force",
                    str(ref.root),
                )
            except RuntimeError as exc:
                # ``apply`` and ``finalize`` can both ask to clean the same
                # worktree; git reports "not a working tree" on the second call.
                if "not a working tree" not in str(exc):
                    raise

        if ref.worktree_ref:
            await self._remove_branch_if_present(ref.worktree_ref)

    def _ensure_safe_root(self, ref: SandboxRef) -> None:
        workspace_parent = Path(self._workspace.root).resolve().parent
        sandbox_root = Path(ref.root).resolve()

        if sandbox_root.parent != workspace_parent:
            raise ValueError(
                "Sandbox root is outside the workspace parent directory"
            )
        if not sandbox_root.name.startswith(".sprout-"):
            raise ValueError("Sandbox root does not use the expected prefix")
        if ref.worktree_ref and not ref.worktree_ref.startswith("sprout-sandbox-"):
            raise ValueError("Sandbox branch does not use the expected prefix")

    async def _remove_branch_if_present(self, branch_name: str) -> None:
        try:
            await self._run(
                "git",
                "-C",
                str(self._workspace.root),
                "branch",
                "-D",
                branch_name,
            )
        except RuntimeError as exc:
            detail = str(exc).lower()
            if "branch" not in detail and "not found" not in detail:
                raise

    @staticmethod
    async def _run(*args: str) -> str:
        # The hardened ``-c`` pins belong right after the program name, so they
        # are injected here rather than at every call site.
        argv = (args[0], *git_args(*args[1:])) if args[:1] == ("git",) else args
        code, stdout, stderr = await run_capture(*argv, env=git_env())
        if code != 0:
            detail = stderr.strip()
            raise RuntimeError(detail or f"git command failed with code {code}")
        return stdout


def _language_command(language: str, code: str) -> tuple[str, tuple[str, ...]]:
    normalized = language.strip().casefold()
    if normalized in {"python", "py"}:
        return sys.executable, ("-c", code)
    if normalized in {"javascript", "js", "node"}:
        return "node", ("-e", code)
    if normalized in {"bash", "sh", "shell"}:
        return "bash", ("-lc", code)
    if normalized in {"ruby", "rb"}:
        return "ruby", ("-e", code)
    if normalized in {"php"}:
        return "php", ("-r", code)
    raise ValueError(f"Unsupported sandbox language: {language}")

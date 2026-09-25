"""Built-in filesystem and CLI tools used by the agent.

These tools wrap common developer operations without using a shell:

- ``grep_check`` searches text files.
- ``cli_tool_detect``, ``cli_tool_download``, and ``cli_tool_run`` manage
  third-party command-line tools.
- ``git_inspect`` and ``git_write`` cover read-only and state-changing git work.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from Sprout.security.net_guard import NetworkGuard
from Sprout.security.secret_broker import SecretBroker
from Sprout.tools.context_keys import CONTEXT_KEY as _CONTEXT_KEY
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec

_MAX_OUTPUT_BYTES = 40_000
_DEFAULT_TIMEOUT = 30.0


def _schema(properties: Mapping[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": required}


def _default_child_env() -> dict[str, str]:
    """Whitelisted subprocess environment — never the parent's own.

    ``_run_command`` has several callers; any that omit ``env=`` used to hand
    the child the entire parent environment, every declared API key included.
    Building a whitelist here keeps the promise the docstring makes below.
    """
    return SecretBroker().child_env(base_env=os.environ)


async def _run_command(
    program: str,
    arguments: list[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    """Run one command without a shell and return decoded stdout/stderr.

    ``env`` is passed through unchanged; callers that need a subprocess
    environment must build one explicitly (``SecretBroker.child_env``), never
    inherit the parent's.
    """
    process = await asyncio.create_subprocess_exec(
        program,
        *arguments,
        cwd=cwd,
        env=dict(env) if env is not None else _default_child_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _clip(value: str) -> str:
    """Keep command output readable for the model."""
    encoded = value.encode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def _workspace_for(path: str | Path, workspace_id: str = "") -> Any:
    """Build a minimal Workspace from a path for broker-based tool delegation."""
    from Sprout.workspace.models import Workspace, WorkspaceKind

    root = Path(path).expanduser().resolve()
    kind = (
        WorkspaceKind.GIT_REPOSITORY
        if (root / ".git").exists()
        else WorkspaceKind.LOCAL_DIRECTORY
    )
    return Workspace(id=workspace_id, root=root, kind=kind)


def _git_result_to_tool_result(result: Any) -> ToolResult:
    if not result.allowed:
        return ToolResult.denied(result.reason or "Git operation not allowed")
    return ToolResult.success(result.output)


class GrepCheckTool:
    """Search files with ``grep``, falling back to ripgrep when available."""

    spec = ToolSpec(
        name="grep_check",
        description="Search text files in the workspace for a regular-expression "
        "pattern. This is a read-only inspection tool.",
        input_schema=_schema(
            {
                "pattern": {"type": "string", "description": "Regular expression to search for."},
                "path": {
                    "type": "string",
                    "description": "File or directory to search.",
                    "default": ".",
                },
                "include": {
                    "type": "string",
                    "description": "Optional glob such as '*.py' or '*.md'.",
                },
                "context": {
                    "type": "integer",
                    "description": "Lines of context to show around each match.",
                    "default": 0,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches per searched file.",
                    "default": 100,
                },
            },
            ["pattern"],
        ),
        risk_level="low",
    )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return ToolResult.failure("Argument 'pattern' must be a non-empty string")
        path = str(arguments.get("path") or ".")
        include = arguments.get("include")
        context = _as_int(arguments.get("context"), default=0, minimum=0)
        max_results = _as_int(arguments.get("max_results"), default=100, minimum=1)

        grep = shutil.which("grep")
        if grep:
            args = ["-n", "-I", "--color=never", "-E", "-r"]
            if include:
                args.extend(["--include", str(include)])
            if context:
                args.extend(["-C", str(context)])
            if max_results:
                args.extend(["-m", str(max_results)])
            args.extend([pattern, path])
        else:
            rg = shutil.which("rg")
            if not rg:
                return ToolResult.failure("Neither grep nor rg was found on PATH")
            args = [
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--max-count",
                str(max_results),
            ]
            if include:
                args.extend(["--glob", str(include)])
            if context:
                args.extend(["--context", str(context)])
            args.extend([pattern, path])
            grep = rg

        try:
            returncode, stdout, stderr = await _run_command(
                grep, args, cwd=str(Path.cwd()), timeout=30.0
            )
        except TimeoutError:
            return ToolResult.failure("grep timed out")
        if returncode == 1:
            return ToolResult.success("No matches found.")
        if returncode != 0:
            return ToolResult.failure(_clip(stderr or f"grep exited with code {returncode}"))
        return ToolResult.success(_clip(stdout), data={"matches": _match_lines(stdout)})


class CliDetectTool:
    """Detect whether a third-party CLI executable is installed."""

    # ``cli_tool_detect`` is declared LOW risk (no approval), so the arguments
    # it forwards to a detected binary must be provably benign. Without this
    # allowlist a caller could run any on-PATH binary with any arguments
    # (``python -c '<payload>'``, ``bash -c '<payload>'``) and get unapproved
    # code execution. Only version/help flags are accepted.
    _VERSION_ARGS_ALLOWLIST = frozenset(
        {"--version", "-V", "-v", "--help", "-h", "version", "help"}
    )

    spec = ToolSpec(
        name="cli_tool_detect",
        description="Check whether a third-party command-line tool is installed "
        "and, optionally, read its version.",
        input_schema=_schema(
            {
                "command": {"type": "string", "description": "Executable name to locate."},
                "version_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional arguments used to request a version, "
                    "such as ['--version'].",
                    "default": ["--version"],
                },
            },
            ["command"],
        ),
        risk_level="low",
    )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult.failure("Argument 'command' must be a non-empty string")
        executable = shutil.which(command)
        payload = {"command": command, "found": executable is not None, "path": executable}
        if not executable:
            return ToolResult.success(
                f"{command!r} was not found on PATH.",
                data=payload,
            )
        version_args = arguments.get("version_args", ["--version"])
        if not isinstance(version_args, list) or not all(
            isinstance(item, str) for item in version_args
        ):
            version_args = ["--version"]
        rejected = [
            arg for arg in version_args if arg not in self._VERSION_ARGS_ALLOWLIST
        ]
        if rejected:
            return ToolResult.failure(
                "version_args may only contain version/help flags "
                f"({', '.join(sorted(self._VERSION_ARGS_ALLOWLIST))}); "
                f"refused: {rejected}"
            )
        try:
            _, stdout, stderr = await _run_command(
                executable, version_args, timeout=10.0
            )
            version = _clip((stdout or stderr).strip().splitlines()[0])
        except (TimeoutError, OSError, ValueError, IndexError):
            version = "unknown"
        payload["version"] = version
        return ToolResult.success(
            f"{command!r} is available at {executable} (version: {version}).",
            data=payload,
        )


class CliDownloadTool:
    """Download a third-party CLI executable into the workspace."""

    spec = ToolSpec(
        name="cli_tool_download",
        description="Download a third-party CLI executable from a URL into the "
        "workspace. The URL is checked against the SSRF guard, redirects are not "
        "followed, and the downloaded file is never marked executable.",
        input_schema=_schema(
            {
                "url": {"type": "string", "description": "HTTP or HTTPS download URL."},
                "destination": {
                    "type": "string",
                    "description": "Relative workspace path for the downloaded file.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace the destination if it already exists.",
                    "default": False,
                },
            },
            ["url"],
        ),
        # Downloads used to be "medium", which the default allow-medium policy
        # auto-approves. Fetching an arbitrary binary into the workspace is the
        # bypass of the process allowlist, so it asks a human first.
        risk_level="high",
    )

    def __init__(
        self,
        *,
        guard: NetworkGuard | None = None,
        network_broker: Any | None = None,
    ) -> None:
        self._guard = guard or NetworkGuard()
        self._network_broker = network_broker

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        url = arguments.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return ToolResult.failure("Argument 'url' must be an http:// or https:// URL")

        verdict = await self._guard.acheck(url)
        if not verdict.allowed:
            return ToolResult.denied(f"Download blocked: {verdict.reason or url}")

        destination = arguments.get("destination")
        cwd = Path.cwd().resolve()
        if destination:
            target = (cwd / str(destination)).resolve()
            try:
                target.relative_to(cwd)
            except ValueError:
                return ToolResult.failure("'destination' must stay inside the workspace")
        else:
            filename = Path(url.split("?", 1)[0]).name or "downloaded-cli"
            target = cwd / "data" / "cli_tools" / filename
        if target.exists() and not arguments.get("overwrite", False):
            return ToolResult.failure(f"Destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if self._network_broker is not None:
            result = await self._network_broker.download(
                _workspace_for(cwd),
                url,
                target,
            )
            if not result.allowed:
                return ToolResult.denied(result.reason or "Download blocked")
            return ToolResult.success(
                f"Downloaded {url} to {target}.",
                data={"path": str(target), "bytes": target.stat().st_size},
            )
        try:
            # ``follow_redirects`` stays off: following a redirect would leave
            # the guarded URL behind and reach a host the guard never saw.
            async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        return ToolResult.denied(
                            f"Download blocked: {url} redirects to {location}"
                        )
                    response.raise_for_status()
                    with target.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
        except Exception as exc:  # noqa: BLE001 - network/download errors are tool results
            return ToolResult.failure(f"Download failed: {type(exc).__name__}: {exc}")
        # Deliberately no ``chmod +x``: the old unconditional bit turned
        # "download" into "download and make runnable", which is exactly the
        # combination the command allowlist refuses to carry.
        return ToolResult.success(
            f"Downloaded {url} to {target}.",
            data={"path": str(target), "bytes": target.stat().st_size},
        )


class CliRunTool:
    """Run an installed CLI command, including Sprout's own CLI."""

    spec = ToolSpec(
        name="cli_tool_run",
        description="Run a CLI executable such as Sprout's `sprout` command with "
        "explicit arguments. "
        "This tool never uses a shell; the child process gets a whitelisted "
        "environment and must run inside an allowed workspace root.",
        input_schema=_schema(
            {
                "command": {"type": "string", "description": "Executable name or workspace path."},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments passed to the executable.",
                    "default": [],
                },
                "cwd": {"type": "string", "description": "Working directory.", "default": "."},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds.",
                    "default": 30,
                },
                "env": {
                    "type": "object",
                    "description": "Additional environment variables.",
                    "default": {},
                },
            },
            ["command"],
        ),
        risk_level="high",
    )

    def __init__(
        self,
        *,
        secrets: SecretBroker | None = None,
        allowed_roots: Sequence[str | Path] | None = None,
        process_broker: Any | None = None,
    ) -> None:
        self._secrets = secrets or SecretBroker()
        roots = allowed_roots if allowed_roots is not None else (Path.cwd(),)
        self._allowed_roots = tuple(Path(root).resolve() for root in roots)
        self._process_broker = process_broker

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult.failure("Argument 'command' must be a non-empty string")
        args = arguments.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            return ToolResult.failure("'args' must be an array of strings")
        cwd_value = str(arguments.get("cwd") or ".")
        cwd = Path(cwd_value).expanduser().resolve()
        if not cwd.is_dir():
            return ToolResult.failure(f"Working directory does not exist: {cwd}")
        if not self._is_allowed_cwd(cwd):
            return ToolResult.denied(
                "Working directory is outside the allowed roots: "
                + ", ".join(str(root) for root in self._allowed_roots)
            )
        timeout = _as_number(arguments.get("timeout"), default=30.0, minimum=0.1)
        executable = shutil.which(command)
        if not executable:
            candidate = Path(command).expanduser().resolve()
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            return ToolResult.failure(f"Executable not found: {command}")
        extra_env = arguments.get("env", {})
        if not isinstance(extra_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in extra_env.items()
        ):
            extra_env = {}
        # A whitelist, never ``os.environ.copy()``: inheriting the parent
        # environment handed every API key in the process to a subprocess that
        # a single approval had unlocked.
        env = self._secrets.child_env(base_env=os.environ, extra=extra_env)
        if self._process_broker is not None:
            return await self._run_via_broker(
                executable, args, cwd, env, timeout, arguments.get(_CONTEXT_KEY)
            )
        try:
            returncode, stdout, stderr = await _run_command(
                executable, args, cwd=str(cwd), env=env, timeout=timeout
            )
        except TimeoutError:
            return ToolResult.failure(f"Command timed out after {timeout}s")
        output = _clip(stdout)
        if stderr.strip():
            output += "\n[stderr]\n" + _clip(stderr)
        if returncode == 0:
            return ToolResult.success(output, data={"returncode": returncode})
        return ToolResult.failure(
            f"Command exited with code {returncode}\n{output}",
        )

    async def _run_via_broker(
        self,
        executable: str,
        args: list[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        context: Any = None,
    ) -> ToolResult:
        """Hand the command to the process broker, carrying the calling context.

        ``context`` is what ``ToolExecutor`` injected (``_sprout_context``): the
        task id, source and requester the agent loop is working for. Passing them
        through is not optional — the broker applies process policy and honors
        the exact upstream CLI approval when present. Without task and approval
        context it would ask twice for the same invocation, or fail to match a
        task-scoped grant.
        """
        ctx = context if isinstance(context, Mapping) else {}
        workspace = _workspace_for(cwd)
        result = await self._process_broker.run(
            workspace,
            [executable, *args],
            cwd=str(cwd),
            env=env,
            timeout_seconds=timeout,
            task_id=str(ctx.get("task_id", "")),
            session_id=str(ctx.get("session_id", "")),
            source=str(ctx.get("source", "") or "interactive"),
            requested_by=str(ctx.get("requested_by", "") or "system"),
            upstream_approval_granted=bool(ctx.get("approval_granted")),
        )
        if not result.allowed:
            # Preserve a parked approval: the broker asks under its own tool
            # name, so dropping its id would leave the operator with no way to
            # answer the question the broker actually asked.
            if getattr(result, "approval_id", ""):
                return ToolResult.needs_approval(result.approval_id)
            return ToolResult.denied(result.error or "Process not allowed")
        output = _clip(result.stdout)
        if result.stderr.strip():
            output += "\n[stderr]\n" + _clip(result.stderr)
        if result.exit_code == 0:
            return ToolResult.success(output, data={"returncode": result.exit_code})
        return ToolResult.failure(
            f"Command exited with code {result.exit_code}\n{output}",
        )

    def _is_allowed_cwd(self, cwd: Path) -> bool:
        """True when ``cwd`` sits inside one of this tool's allowed roots."""
        for root in self._allowed_roots:
            if cwd == root or cwd.is_relative_to(root):
                return True
        return False


class SkillScriptTool:
    """Run a script bundled inside a standard skill directory."""

    def __init__(self, skills_dir: str | Path) -> None:
        self._skills_dir = Path(skills_dir).expanduser().resolve()
        self.spec = ToolSpec(
            name="skill_script",
            description="Run a script that belongs to a standard skill directory.",
            input_schema=_schema(
                {
                    "skill": {"type": "string", "description": "Skill directory name."},
                    "script": {
                        "type": "string",
                        "description": "Relative script path inside the skill.",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Arguments passed to the script.",
                        "default": [],
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds.",
                        "default": 30,
                    },
                },
                ["skill", "script"],
            ),
            risk_level="high",
        )

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        from Sprout.orchestration.terminal.ensure import ensure_temporal_async

        try:
            await ensure_temporal_async()
        except RuntimeError as exc:
            return ToolResult.failure(str(exc))
        skill = arguments.get("skill")
        script = arguments.get("script")
        if not isinstance(skill, str) or not skill.strip():
            return ToolResult.failure("Argument 'skill' must be a non-empty string")
        if not isinstance(script, str) or not script.strip():
            return ToolResult.failure("Argument 'script' must be a non-empty string")
        args = arguments.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            return ToolResult.failure("'args' must be an array of strings")

        skill_root = (self._skills_dir / skill).resolve()
        try:
            skill_root.relative_to(self._skills_dir)
        except ValueError:
            return ToolResult.failure("Skill path escapes the skills directory")
        script_path = (skill_root / script).resolve()
        try:
            script_path.relative_to(skill_root)
        except ValueError:
            return ToolResult.failure("Script path escapes the skill directory")
        if not script_path.is_file():
            return ToolResult.failure(f"Skill script not found: {script_path}")

        executable = shutil.which(str(script_path))
        if executable is None:
            if script_path.suffix == ".py":
                executable = sys.executable
                args = [str(script_path), *args]
            elif os.access(script_path, os.X_OK):
                executable = str(script_path)
            else:
                return ToolResult.failure(
                    f"Skill script is not executable: {script_path}"
                )
        else:
            args = [str(script_path), *args]

        timeout = _as_number(arguments.get("timeout"), default=30.0, minimum=0.1)
        try:
            returncode, stdout, stderr = await _run_command(
                executable,
                args,
                cwd=str(skill_root),
                timeout=timeout,
            )
        except TimeoutError:
            return ToolResult.failure(f"Skill script timed out after {timeout}s")
        output = _clip(stdout)
        if stderr.strip():
            output += "\n[stderr]\n" + _clip(stderr)
        if returncode == 0:
            return ToolResult.success(output, data={"returncode": returncode})
        return ToolResult.failure(
            f"Skill script exited with code {returncode}\n{output}"
        )


class GitInspectTool:
    """Read-only git operations."""

    _OPERATIONS = {
        "status",
        "log",
        "branch",
        "diff",
        "show",
        "remote",
        "tag",
        "stash_list",
        "rev_parse",
        "ls_files",
    }

    spec = ToolSpec(
        name="git_inspect",
        description=(
            "Inspect a git repository: status, log, branches, diff, show, remotes, "
            "tags, stash list, revision parsing, or tracked file lists."
        ),
        input_schema=_schema(
            {
                "operation": {
                    "type": "string",
                    "enum": sorted(_OPERATIONS),
                    "description": "Which read-only git view to return.",
                },
                "repo": {"type": "string", "description": "Repository path.", "default": "."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum log entries for 'log'.",
                    "default": 20,
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional files for 'diff'.",
                    "default": [],
                },
                "ref": {
                    "type": "string",
                    "description": "Revision/ref for show, diff, log, or rev_parse.",
                    "default": "",
                },
                "base": {
                    "type": "string",
                    "description": "Base revision for diff.",
                    "default": "",
                },
                "name_only": {
                    "type": "boolean",
                    "description": "Use --name-only for diff or ls-files style output.",
                    "default": False,
                },
                "untracked": {
                    "type": "boolean",
                    "description": "Include untracked files for ls_files.",
                    "default": False,
                },
            },
            ["operation"],
        ),
        risk_level="low",
    )

    def __init__(self, *, git_broker: Any | None = None) -> None:
        self._git_broker = git_broker

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        operation = arguments.get("operation")
        if operation not in self._OPERATIONS:
            return ToolResult.failure(
                f"Invalid operation; expected one of: {', '.join(sorted(self._OPERATIONS))}"
            )
        repo = str(arguments.get("repo") or ".")
        if self._git_broker is not None and operation in {"status", "log", "branch", "diff"}:
            workspace = _workspace_for(repo)
            if operation == "status":
                result = await self._git_broker.status(workspace)
            elif operation == "log":
                result = await self._git_broker.log(
                    workspace,
                    _as_int(arguments.get("limit"), 20, 1),
                )
            elif operation == "branch":
                result = await self._git_broker.branch(workspace)
            elif operation == "diff":
                result = await self._git_broker.diff(workspace)
            return _git_result_to_tool_result(result)
        args = ["-C", repo]
        if operation == "status":
            args.extend(["status", "--short", "--branch"])
        elif operation == "log":
            args.extend(
                [
                    "log",
                    "--oneline",
                    "--decorate",
                    "-n",
                    str(_as_int(arguments.get("limit"), 20, 1)),
                ]
            )
            ref = _safe_git_ref(arguments.get("ref"))
            if ref:
                args.append(ref)
        elif operation == "branch":
            args.extend(["branch", "--all", "-vv"])
        elif operation == "diff":
            args.append("diff")
            if _as_bool(arguments.get("name_only")):
                args.append("--name-only")
            base = _safe_git_ref(arguments.get("base"))
            ref = _safe_git_ref(arguments.get("ref"))
            if base and ref:
                args.append(f"{base}..{ref}")
            elif base:
                args.append(base)
            elif ref:
                args.append(ref)
            files = arguments.get("files", [])
            if files:
                args.extend(["--", *_string_list(files)])
            elif not _as_bool(arguments.get("name_only")) and not (base or ref):
                args.append("--stat")
        elif operation == "show":
            ref = _safe_git_ref(arguments.get("ref")) or "HEAD"
            args.extend(["show", "--stat", "--oneline", ref])
        elif operation == "remote":
            args.extend(["remote", "-v"])
        elif operation == "tag":
            args.extend(["tag", "--list"])
        elif operation == "stash_list":
            args.extend(["stash", "list"])
        elif operation == "rev_parse":
            ref = _safe_git_ref(arguments.get("ref")) or "HEAD"
            args.extend(["rev-parse", "--verify", ref])
        elif operation == "ls_files":
            args.extend(["ls-files"])
            if _as_bool(arguments.get("untracked")):
                args.extend(["--others", "--exclude-standard"])
        return await _run_git(args)


class GitWriteTool:
    """State-changing git operations requiring high-risk approval."""

    _OPERATIONS = {
        "add",
        "commit",
        "pull",
        "fetch",
        "push",
        "checkout",
        "switch",
        "branch_create",
        "branch_delete",
        "merge",
        "rebase",
        "reset",
        "restore",
        "revert",
        "stash_push",
        "stash_apply",
        "stash_pop",
        "stash_drop",
        "tag_create",
        "tag_delete",
        "clone",
    }

    spec = ToolSpec(
        name="git_write",
        description=(
            "Perform state-changing git operations with approval: add, commit, pull, "
            "fetch, push, checkout/switch, branch, merge/rebase, reset/restore/revert, "
            "stash, tag, or clone."
        ),
        input_schema=_schema(
            {
                "operation": {
                    "type": "string",
                    "enum": sorted(_OPERATIONS),
                    "description": "Git write operation to perform.",
                },
                "repo": {"type": "string", "description": "Repository path.", "default": "."},
                "message": {
                    "type": "string",
                    "description": "Commit message; required for 'commit'.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional files to stage.",
                    "default": [],
                },
                "ref": {"type": "string", "description": "Revision/ref/branch.", "default": ""},
                "branch": {"type": "string", "description": "Branch name.", "default": ""},
                "remote": {"type": "string", "description": "Remote name.", "default": "origin"},
                "upstream": {"type": "string", "description": "Upstream branch.", "default": ""},
                "mode": {
                    "type": "string",
                    "enum": ["soft", "mixed", "hard"],
                    "description": "Reset mode.",
                    "default": "mixed",
                },
                "stash": {
                    "type": "string",
                    "description": "Stash ref such as stash@{0}.",
                    "default": "",
                },
                "tag": {"type": "string", "description": "Tag name.", "default": ""},
                "url": {"type": "string", "description": "Remote URL for clone.", "default": ""},
                "directory": {
                    "type": "string",
                    "description": "Target directory for clone.",
                    "default": "",
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": "Set upstream when pushing.",
                    "default": False,
                },
            },
            ["operation"],
        ),
        risk_level="high",
    )

    def __init__(self, *, git_broker: Any | None = None) -> None:
        self._git_broker = git_broker

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        operation = arguments.get("operation")
        if operation not in self._OPERATIONS:
            return ToolResult.failure(
                f"Invalid operation; expected one of: {', '.join(sorted(self._OPERATIONS))}"
            )
        repo = str(arguments.get("repo") or ".")
        if self._git_broker is not None and operation in {"add", "commit", "pull"}:
            workspace = _workspace_for(repo)
            files = tuple(
                item for item in arguments.get("files", []) if isinstance(item, str)
            )
            if operation == "add":
                result = await self._git_broker.add(workspace, files)
            elif operation == "pull":
                result = await self._git_broker.pull(workspace)
            elif operation == "commit":
                message = arguments.get("message")
                if not isinstance(message, str) or not message.strip():
                    return ToolResult.failure("'message' is required for git commit")
                result = await self._git_broker.commit(
                    workspace,
                    message,
                    files=files,
                )
            return _git_result_to_tool_result(result)
        files = arguments.get("files", [])
        if files:
            try:
                files = _string_list(files)
            except ValueError as exc:
                return ToolResult.failure(str(exc))
        args = ["-C", repo]
        if operation == "pull":
            remote = _safe_git_ref(arguments.get("remote")) or "origin"
            upstream = _safe_git_ref(arguments.get("upstream"))
            pull_args = [*args, "pull", "--ff-only", remote]
            if upstream:
                pull_args.append(upstream)
            return await _run_git(pull_args)
        if operation == "fetch":
            remote = _safe_git_ref(arguments.get("remote")) or "--all"
            return await _run_git([*args, "fetch", remote])
        if operation == "push":
            remote = _safe_git_ref(arguments.get("remote")) or "origin"
            branch = _safe_git_ref(arguments.get("branch"))
            push_args = [*args, "push"]
            if _as_bool(arguments.get("set_upstream")):
                push_args.append("--set-upstream")
            push_args.append(remote)
            if branch:
                push_args.append(branch)
            return await _run_git(push_args)
        if operation == "add":
            return await _run_git([*args, "add", *(files or ["-A"])])
        if operation == "commit":
            message = arguments.get("message")
            if not isinstance(message, str) or not message.strip():
                return ToolResult.failure("'message' is required for git commit")
            staged = await _run_git([*args, "add", *(files or ["-A"])])
            if not staged.ok:
                return staged
            return await _run_git([*args, "commit", "-m", message])
        if operation == "checkout":
            ref = _safe_git_ref(arguments.get("ref")) or _safe_git_ref(arguments.get("branch"))
            if not ref:
                return ToolResult.failure("'ref' or 'branch' is required for git checkout")
            return await _run_git([*args, "checkout", ref])
        if operation == "switch":
            branch = _safe_git_ref(arguments.get("branch")) or _safe_git_ref(arguments.get("ref"))
            if not branch:
                return ToolResult.failure("'branch' is required for git switch")
            return await _run_git([*args, "switch", branch])
        if operation == "branch_create":
            branch = _safe_git_ref(arguments.get("branch"))
            if not branch:
                return ToolResult.failure("'branch' is required for branch_create")
            ref = _safe_git_ref(arguments.get("ref"))
            return await _run_git([*args, "branch", branch, *([ref] if ref else [])])
        if operation == "branch_delete":
            branch = _safe_git_ref(arguments.get("branch"))
            if not branch:
                return ToolResult.failure("'branch' is required for branch_delete")
            return await _run_git([*args, "branch", "-d", branch])
        if operation == "merge":
            ref = _safe_git_ref(arguments.get("ref")) or _safe_git_ref(arguments.get("branch"))
            if not ref:
                return ToolResult.failure("'ref' or 'branch' is required for git merge")
            return await _run_git([*args, "merge", "--no-edit", ref])
        if operation == "rebase":
            ref = _safe_git_ref(arguments.get("ref")) or _safe_git_ref(arguments.get("branch"))
            if not ref:
                return ToolResult.failure("'ref' or 'branch' is required for git rebase")
            return await _run_git([*args, "rebase", ref])
        if operation == "reset":
            mode = str(arguments.get("mode") or "mixed")
            if mode not in {"soft", "mixed", "hard"}:
                return ToolResult.failure("'mode' must be soft, mixed, or hard")
            ref = _safe_git_ref(arguments.get("ref")) or "HEAD"
            return await _run_git([*args, "reset", f"--{mode}", ref])
        if operation == "restore":
            restore_args = [*args, "restore"]
            ref = _safe_git_ref(arguments.get("ref"))
            if ref:
                restore_args.extend(["--source", ref])
            restore_args.extend(["--", *(files or ["."])])
            return await _run_git(restore_args)
        if operation == "revert":
            ref = _safe_git_ref(arguments.get("ref"))
            if not ref:
                return ToolResult.failure("'ref' is required for git revert")
            return await _run_git([*args, "revert", "--no-edit", ref])
        if operation == "stash_push":
            stash_args = [*args, "stash", "push"]
            message = arguments.get("message")
            if isinstance(message, str) and message.strip():
                stash_args.extend(["-m", message])
            if files:
                stash_args.extend(["--", *files])
            return await _run_git(stash_args)
        if operation in {"stash_apply", "stash_pop", "stash_drop"}:
            stash = _safe_git_ref(arguments.get("stash")) or "stash@{0}"
            subcommand = operation.removeprefix("stash_")
            return await _run_git([*args, "stash", subcommand, stash])
        if operation == "tag_create":
            tag = _safe_git_ref(arguments.get("tag"))
            if not tag:
                return ToolResult.failure("'tag' is required for tag_create")
            message = arguments.get("message")
            if isinstance(message, str) and message.strip():
                return await _run_git([*args, "tag", "-a", tag, "-m", message])
            return await _run_git([*args, "tag", tag])
        if operation == "tag_delete":
            tag = _safe_git_ref(arguments.get("tag"))
            if not tag:
                return ToolResult.failure("'tag' is required for tag_delete")
            return await _run_git([*args, "tag", "-d", tag])
        if operation == "clone":
            url = arguments.get("url")
            if not isinstance(url, str) or not url.strip():
                return ToolResult.failure("'url' is required for git clone")
            directory = arguments.get("directory")
            clone_args = ["clone", url]
            if isinstance(directory, str) and directory.strip():
                clone_args.append(directory)
            return await _run_git(clone_args)
        return ToolResult.failure(f"Unsupported git operation: {operation}")


async def _run_git(args: list[str]) -> ToolResult:
    git = shutil.which("git")
    if not git:
        return ToolResult.failure("git was not found on PATH")
    try:
        returncode, stdout, stderr = await _run_command(git, args, timeout=30.0)
    except TimeoutError:
        return ToolResult.failure("git command timed out")
    output = _clip(stdout)
    if stderr.strip():
        output += "\n[stderr]\n" + _clip(stderr)
    if returncode == 0:
        return ToolResult.success(output)
    return ToolResult.failure(f"git exited with code {returncode}\n{output}")


def _safe_git_ref(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    ref = value.strip()
    if not ref or ref.startswith("-") or "\0" in ref:
        return ""
    return ref


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("'files' must be an array of strings")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("'files' must be an array of strings")
        result.append(item)
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, minimum)


def _as_number(value: Any, default: float, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, minimum)


def _match_lines(stdout: str) -> list[dict[str, str]]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    matches: list[dict[str, str]] = []
    for line in lines:
        if ":" in line:
            path, rest = line.split(":", 1)
            if ":" in rest:
                number, text = rest.split(":", 1)
                matches.append({"path": path, "line": number, "text": text})
            else:
                matches.append({"path": path, "line": "", "text": rest})
        else:
            matches.append({"path": "", "line": "", "text": line})
    return matches

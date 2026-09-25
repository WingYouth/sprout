"""CLI-backed skill sources (design §7.3).

Remote sources fetch through the local CLI (``git``, ``curl``) rather than a
bespoke HTTP client: the machine's existing credentials, proxies and git config
are reused, and every invocation can be routed through
:class:`~Sprout.execution.ProcessBroker` so policy, approvals and audit apply
exactly as they do for any other command the agent runs.

:class:`SubprocessRunner` is the plain fallback used when no broker is wired
(unit tests, one-off CLI use); :class:`ProcessBrokerRunner` adapts the process
broker for ``git``, and :class:`NetworkBrokerRunner` adapts the network broker
for ``curl`` so an HTTP fetch is audited and SSRF-guarded *without* needing an
approval (``network.get`` is ``ALLOW`` in the matrix). A source only ever
*fetches* — nothing is installed here (design §7.4).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from Sprout.security.secret_broker import SecretBroker


@dataclass(frozen=True, slots=True)
class CliResult:
    """Captured output of one CLI invocation."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@runtime_checkable
class CliRunner(Protocol):
    """Runs an argv and returns its captured output."""

    async def run(
        self, argv: list[str], *, cwd: str | None = None, timeout: float = 60.0
    ) -> CliResult: ...


class SubprocessRunner:
    """Plain ``asyncio`` subprocess runner — no policy layer.

    Used by tests and by direct CLI use where no :class:`ProcessBroker` has been
    assembled. It does not check the policy matrix or ask for approval; a caller
    that needs those must wire :class:`ProcessBrokerRunner` instead.

    The child gets the same **whitelisted** environment the broker builds, so
    this fallback cannot leak a declared secret into a download it performs.
    That was the documented behaviour but not the implemented one: no ``env=``
    was passed, so the child inherited everything.
    """

    async def run(
        self, argv: list[str], *, cwd: str | None = None, timeout: float = 60.0
    ) -> CliResult:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=SecretBroker().child_env(base_env=os.environ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"{argv[0]} timed out after {timeout}s") from None
        return CliResult(
            argv=tuple(argv),
            exit_code=proc.returncode or 0,
            stdout=out.decode("utf-8", "replace"),
            stderr=err.decode("utf-8", "replace"),
        )


class ProcessBrokerRunner:
    """Route CLI fetches through :class:`ProcessBroker` (policy + approvals + audit).

    A denial surfaces as :class:`PermissionError` so a source can never quietly
    proceed with a command the policy refused.
    """

    def __init__(
        self,
        broker: Any,
        workspace: Any,
        *,
        task_id: str = "",
        cwd: str | None = None,
    ) -> None:
        self._broker = broker
        self._workspace = workspace
        self._task_id = task_id
        self._cwd = cwd

    async def run(
        self, argv: list[str], *, cwd: str | None = None, timeout: float = 60.0
    ) -> CliResult:
        result = await self._broker.run(
            self._workspace,
            list(argv),
            cwd=cwd or self._cwd,
            timeout_seconds=timeout,
            task_id=self._task_id,
        )
        if not result.allowed:
            raise PermissionError(result.error or "process denied by policy")
        return CliResult(
            argv=tuple(argv),
            exit_code=result.exit_code or 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )


class NetworkBrokerRunner:
    """Route ``curl`` fetches through :class:`NetworkBroker` (policy + URL guard).

    ``network.get`` is ``ALLOW`` in the matrix, so a broker-routed download still
    happens *without* an approval — but it is now audited, and
    :class:`~Sprout.security.net_guard.NetworkGuard` refuses private, loopback,
    link-local (``169.254.169.254``) and CGNAT targets, so a skill URL cannot be
    turned into an SSRF primitive against the host or the cloud metadata service.

    Only the HTTP subset of ``curl`` that a source actually emits is understood;
    anything else raises, so this runner can never be mistaken for a shell.
    """

    def __init__(self, broker: Any, workspace: Any, *, task_id: str = "") -> None:
        self._broker = broker
        self._workspace = workspace
        self._task_id = task_id

    async def run(
        self, argv: list[str], *, cwd: str | None = None, timeout: float = 60.0
    ) -> CliResult:
        url, target = parse_curl(argv)
        result = await self._broker.get(self._workspace, url, task_id=self._task_id)
        if not result.allowed:
            raise PermissionError(result.reason or "network GET denied by policy")
        if result.status_code is not None and result.status_code >= 400:
            # Mirror ``curl --fail`` (exit 22) so a failed fetch is never parsed.
            return CliResult(
                argv=tuple(argv),
                exit_code=22,
                stderr=f"HTTP {result.status_code} for {url}",
            )
        if target is not None:
            Path(target).write_text(result.body, encoding="utf-8")
        return CliResult(
            argv=tuple(argv),
            exit_code=0,
            stdout="" if target is not None else result.body,
        )


def parse_curl(argv: list[str]) -> tuple[str, str | None]:
    """Pull the URL and the ``-o`` target out of a ``curl`` argv.

    Returns ``(url, output_path_or_None)``. A non-``curl`` command raises so the
    caller fails loudly instead of quietly fetching nothing.
    """
    if not argv or Path(argv[0]).name not in {"curl", "curl.exe"}:
        raise ValueError(f"NetworkBrokerRunner only handles curl, got {argv[:1]!r}")
    url: str | None = None
    target: str | None = None
    args = argv[1:]
    for index, arg in enumerate(args):
        lowered = arg.lower()
        if arg in {"-o", "--output"}:
            target = args[index + 1] if index + 1 < len(args) else None
        elif lowered.startswith("--output="):
            target = arg.split("=", 1)[1]
        elif lowered.startswith(("http://", "https://")):
            url = arg
    if url is None:
        raise ValueError(f"no URL in curl argv: {argv!r}")
    return url, target


async def fetch_url_as_dir(
    runner: CliRunner,
    url: str,
    *,
    name: str,
    source: str,
    timeout: float = 60.0,
) -> Any:
    """Download one ``SKILL.md`` over the CLI into a scratch dir and parse it.

    Reuses :class:`~Sprout.skills.sources.local.LocalDirSource` for the parse
    step so a remote fetch produces exactly the same bundle shape as a local
    directory — one parsing path, not two.
    """
    from Sprout.skills.sources.base import SkillStub
    from Sprout.skills.sources.local import LocalDirSource

    workdir = Path(tempfile.mkdtemp(prefix="sprout-skill-"))
    try:
        target = workdir / "SKILL.md"
        result = await runner.run(
            ["curl", "-fsSL", url, "-o", str(target)], timeout=timeout
        )
        if not result.ok:
            raise RuntimeError(
                f"download failed ({result.exit_code}): {result.stderr.strip()}"
            )
        local = LocalDirSource(workdir, source=source)
        return await local.fetch(
            SkillStub(name=name, source=source, origin=str(workdir))
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

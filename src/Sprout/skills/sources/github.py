"""GitHub skill source (design §7.3): ``owner/repo[:path]`` cloned via the git CLI."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.sources.cli import CliResult, CliRunner, SubprocessRunner
from Sprout.skills.sources.local import LocalDirSource

logger = logging.getLogger("sprout.skills")

#: Substrings that mark a *transient* transport failure: the network dropped the
#: connection mid-handshake. Measured on a real link, ``git clone`` against
#: GitHub fails this way a few times an hour and then succeeds on the next
#: attempt, so treating it as fatal turns a blip into "this skill is
#: uninstallable". A deterministic failure — repository not found, auth denied —
#: is deliberately *not* in this list, because retrying it only wastes time.
_TRANSIENT_MARKERS = (
    "unexpected eof while reading",
    "ssl routines",
    "tls connect error",
    "gnutls_handshake",
    "connection reset by peer",
    "connection timed out",
    "operation timed out",
    "could not resolve host",
    "early eof",
    "rpc failed",
    "the remote end hung up unexpectedly",
    "fetch-pack: unexpected disconnect",
    "http/2 stream",
    "temporary failure in name resolution",
)

#: Deterministic failures. Retrying these cannot help, and a slow retry loop in
#: front of "no such repository" just delays a clear error.
_PERMANENT_MARKERS = (
    # Git's wording varies with the transport: ``repository 'URL' not found``
    # for HTTPS, ``Repository not found`` for the API. Match the ending, not the
    # whole sentence — an earlier, more literal marker silently failed to match
    # the real message and let a 404 be retried three times.
    "not found",
    "could not read username",
    "authentication failed",
    "permission denied",
    "not a git repository",
    "couldn't find remote ref",
    "invalid refspec",
    "access denied",
)

_GITHUB_PREFIXES = (
    "https://github.com/",
    "http://github.com/",
    "github.com/",
    "git@github.com:",
    # The origin form marketplace discovery records, e.g.
    # ``github:anthropics/skills/skills/pdf``.
    "github:",
)


def split_ref(query: str) -> tuple[str, str, str]:
    """``owner/repo`` or ``owner/repo/path`` -> ``(owner, repo, subpath)``."""
    cleaned = query.strip()
    for prefix in _GITHUB_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"expected owner/repo[:path], got {query!r}")
    owner, repo, *rest = parts
    return owner, repo.removesuffix(".git"), "/".join(rest)


def is_transient_failure(result: CliResult) -> bool:
    """True when retrying this failed ``git`` invocation could plausibly work.

    Kept as a module function so callers and tests can classify a result without
    constructing a source.
    """
    if result.ok:
        return False
    text = f"{result.stderr}\n{result.stdout}".casefold()
    if any(marker in text for marker in _PERMANENT_MARKERS):
        return False
    return any(marker in text for marker in _TRANSIENT_MARKERS)


class GitHubSource:
    """Fetch a skill from GitHub with the local ``git`` CLI (no HTTP client)."""

    name = "github"

    def __init__(
        self,
        *,
        runner: CliRunner | None = None,
        timeout: float = 180.0,
        attempts: int = 3,
        backoff_seconds: float = 0.75,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._timeout = timeout
        #: A dropped TLS handshake is routine on a real link, so a single clone
        #: attempt is not a reliable probe of whether a skill can be installed.
        self._attempts = max(1, attempts)
        self._backoff = max(0.0, backoff_seconds)

    async def _run_with_retry(
        self, argv: list[str], *, timeout: float | None = None
    ) -> CliResult:
        """Run ``argv``, retrying only transient transport failures."""
        limit = timeout or self._timeout
        result = await self._runner.run(argv, timeout=limit)
        for attempt in range(2, self._attempts + 1):
            if not is_transient_failure(result):
                return result
            delay = self._backoff * (2 ** (attempt - 2))
            logger.info(
                "Transient git failure (attempt %d/%d), retrying in %.2fs: %s",
                attempt - 1,
                self._attempts,
                delay,
                result.stderr.strip()[:200],
            )
            if delay:
                await asyncio.sleep(delay)
            result = await self._runner.run(argv, timeout=limit)
        return result

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        owner, repo, subpath = split_ref(query)
        slug = f"{owner}/{repo}" + (f"/{subpath}" if subpath else "")
        name = subpath.rsplit("/", 1)[-1] if subpath else repo
        return [
            SkillStub(
                name=name,
                source=self.name,
                origin=slug,
                description=f"GitHub: {slug}",
            )
        ][:limit]

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        owner, repo, subpath = split_ref(stub.origin)
        workdir = Path(tempfile.mkdtemp(prefix="sprout-skill-"))
        try:
            checkout = workdir / repo
            # ``--filter=blob:none --sparse`` downloads the tree, not the tree's
            # contents: a repository that is 501 MB whole (measured on a real
            # skill repo) clones in well under a megabyte this way. Without it,
            # installing one skill from a large repo means fetching all of them.
            command = [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
            ]
            if stub.ref:
                command += ["--branch", stub.ref]
            command += [f"https://github.com/{owner}/{repo}.git", str(checkout)]
            result = await self._run_with_retry(command)
            if not result.ok:
                raise RuntimeError(
                    f"git clone failed ({result.exit_code}) after "
                    f"{self._attempts} attempt(s): {result.stderr.strip()}"
                )
            if subpath:
                # Materialise only the requested skill directory.
                sparse = await self._run_with_retry(
                    ["git", "-C", str(checkout), "sparse-checkout", "set", subpath]
                )
                if not sparse.ok:
                    raise RuntimeError(
                        f"git sparse-checkout failed ({sparse.exit_code}): "
                        f"{sparse.stderr.strip()}"
                    )
            root = checkout / subpath if subpath else checkout
            local = LocalDirSource(root, source=self.name)
            return await local.fetch(
                SkillStub(name=stub.name, source=self.name, origin=str(root))
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

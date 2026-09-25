"""Transient-failure retry for the GitHub skill source.

A dropped TLS handshake is routine on a real link — measured against GitHub, the
same ``git clone`` fails a few times an hour and then succeeds — so a single
attempt is not a reliable answer to "can this skill be installed". These tests
pin the classification that decides which failures are worth retrying, and prove
that a deterministic failure is returned immediately rather than retried.
"""

from __future__ import annotations

import pytest

from Sprout.skills.sources.cli import CliResult
from Sprout.skills.sources.github import GitHubSource, is_transient_failure

# The real message observed when the connection was cut mid-handshake.
TLS_EOF = (
    "fatal: unable to access 'https://github.com/acme/skills.git/': "
    "TLS connect error: error:0A000126:SSL routines::unexpected eof while reading"
)
NOT_FOUND = "fatal: repository 'https://github.com/acme/gone.git/' not found"
AUTH_FAILED = "fatal: Authentication failed for 'https://github.com/acme/private.git/'"


def _stub(origin: str = "acme/skills"):
    from Sprout.skills.sources.base import SkillStub

    return SkillStub(name="pdf", source="github", origin=origin)


def _ok(argv: tuple[str, ...] = ("git",)) -> CliResult:
    return CliResult(argv=argv, exit_code=0)


def _fail(stderr: str, argv: tuple[str, ...] = ("git",)) -> CliResult:
    return CliResult(argv=argv, exit_code=128, stderr=stderr)


class ScriptedRunner:
    """Returns canned results in order, recording how many calls it saw."""

    def __init__(self, results: list[CliResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def run(self, argv, *, cwd=None, timeout=60.0) -> CliResult:
        self.calls += 1
        if not self._results:
            raise AssertionError("runner called more times than scripted")
        return self._results.pop(0)


# -- classification ------------------------------------------------------------


def test_success_is_never_retried() -> None:
    assert is_transient_failure(_ok()) is False


@pytest.mark.parametrize(
    "stderr",
    [
        TLS_EOF,
        "error:0A000126:SSL routines::unexpected eof while reading",
        "gnutls_handshake() failed: Error in the pull function.",
        "fatal: the remote end hung up unexpectedly",
        "fatal: unable to access ...: Connection reset by peer",
        "error: RPC failed; curl 56 OpenSSL SSL_read: Connection reset by peer",
        "fatal: unable to access ...: Operation timed out",
        "fatal: unable to access ...: Could not resolve host: github.com",
        "fetch-pack: unexpected disconnect while reading sideband packet",
    ],
)
def test_transport_failures_are_transient(stderr: str) -> None:
    assert is_transient_failure(_fail(stderr)) is True


@pytest.mark.parametrize(
    "stderr",
    [
        NOT_FOUND,
        AUTH_FAILED,
        "fatal: Permission denied (publickey).",
        "fatal: not a git repository (or any of the parent directories): .git",
        "fatal: couldn't find remote ref nope",
    ],
)
def test_deterministic_failures_are_not_transient(stderr: str) -> None:
    """Retrying "no such repository" only delays a clear error."""
    assert is_transient_failure(_fail(stderr)) is False


def test_a_permanent_marker_wins_over_a_transient_one() -> None:
    """A 404 body can mention connection details; the verdict must be permanent."""
    mixed = f"{NOT_FOUND}\nconnection reset by peer"

    assert is_transient_failure(_fail(mixed)) is False


# -- retry behaviour -----------------------------------------------------------


async def test_two_transient_failures_then_a_success_is_retried_through() -> None:
    """The blip case: two dropped handshakes, then the clone goes through."""
    runner = ScriptedRunner([_fail(TLS_EOF), _fail(TLS_EOF), _ok()])
    source = GitHubSource(runner=runner, attempts=3, backoff_seconds=0.0)

    result = await source._run_with_retry(["git", "clone"])

    assert result.ok is True
    assert runner.calls == 3


async def test_fetch_reports_the_attempt_count_when_it_gives_up() -> None:
    """A failure after retrying must say so, so the cause is not read as a typo."""
    runner = ScriptedRunner([_fail(TLS_EOF) for _ in range(2)])
    source = GitHubSource(runner=runner, attempts=2, backoff_seconds=0.0)

    with pytest.raises(RuntimeError) as caught:
        await source.fetch(
            _stub(origin="acme/skills/skills/pdf")
        )

    assert "after 2 attempt(s)" in str(caught.value)


async def test_a_deterministic_failure_is_not_retried() -> None:
    runner = ScriptedRunner([_fail(NOT_FOUND)])
    source = GitHubSource(runner=runner, attempts=3, backoff_seconds=0.0)

    result = await source._run_with_retry(["git", "clone"])

    assert result.ok is False
    assert runner.calls == 1, "a missing repository must fail after one attempt"


async def test_retry_stops_after_the_attempt_budget() -> None:
    runner = ScriptedRunner([_fail(TLS_EOF) for _ in range(3)])
    source = GitHubSource(runner=runner, attempts=3, backoff_seconds=0.0)

    result = await source._run_with_retry(["git", "clone"])

    assert result.ok is False
    assert runner.calls == 3
    assert "unexpected eof" in result.stderr


async def test_a_successful_run_is_not_retried() -> None:
    runner = ScriptedRunner([_ok()])
    source = GitHubSource(runner=runner, attempts=3, backoff_seconds=0.0)

    result = await source._run_with_retry(["git", "clone"])

    assert result.ok is True
    assert runner.calls == 1

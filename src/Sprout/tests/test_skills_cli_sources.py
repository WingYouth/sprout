"""``sprout skills`` wiring for the CLI-backed sources (design §7.3, §12).

``GitHubSource`` / ``UrlSource`` / ``WellKnownSource`` existed, but ``_build_source``
only knew ``catalog`` and ``local``, so ``--source github|url|well-known`` silently
fell back to ``LocalDirSource`` and no remote skill was reachable from the CLI at all.

These tests pin that dispatch, and pin the default fetch mode: a human running
``sprout skills`` *is* the operator, so the source's own ``SubprocessRunner`` fetches
directly and ``--via-broker`` is the opt-in policy path.
"""

from __future__ import annotations

from Sprout.cli.commands.skills import _build_runner, _build_source
from Sprout.skills.sources.cli import parse_curl
from Sprout.skills.sources.github import GitHubSource
from Sprout.skills.sources.local import LocalDirSource
from Sprout.skills.sources.url import UrlSource
from Sprout.skills.sources.wellknown import WellKnownSource


def _build(source: str) -> object:
    """``settings=None`` is safe here: ``--dir`` short-circuits the local branch."""
    return _build_source(source, manifest=None, directory=".", settings=None)


def test_github_source_is_reachable_from_the_cli() -> None:
    assert isinstance(_build("github"), GitHubSource)


def test_url_source_is_reachable_from_the_cli() -> None:
    assert isinstance(_build("url"), UrlSource)


def test_well_known_source_is_reachable_under_both_spellings() -> None:
    assert isinstance(_build("well-known"), WellKnownSource)
    assert isinstance(_build("wellknown"), WellKnownSource)


def test_local_source_still_handles_everything_else() -> None:
    assert isinstance(_build("local"), LocalDirSource)
    assert isinstance(_build("evolved"), LocalDirSource)


def test_broker_is_opt_in_so_a_direct_fetch_stays_direct() -> None:
    assert _build_runner(None, source="url", via_broker=False) is None
    assert _build_runner(None, source="github", via_broker=False) is None


def test_parse_curl_reads_the_url_and_the_output_target() -> None:
    """The shape ``fetch_url_as_dir`` emits must round-trip."""
    url, target = parse_curl(["curl", "-fsSL", "https://example.com/a/SKILL.md", "-o", "/tmp/x"])
    assert url == "https://example.com/a/SKILL.md"
    assert target == "/tmp/x"


def test_parse_curl_accepts_the_equals_form() -> None:
    url, target = parse_curl(["curl", "--output=/tmp/x", "https://example.com/SKILL.md"])
    assert url == "https://example.com/SKILL.md"
    assert target == "/tmp/x"


def test_parse_curl_refuses_a_command_it_cannot_honour() -> None:
    """A git clone must never be silently swallowed by the HTTP runner."""
    import pytest

    with pytest.raises(ValueError):
        parse_curl(["git", "clone", "https://example.com/repo"])
    with pytest.raises(ValueError):
        parse_curl(["curl", "-fsSL"])


# -- the plain runner's environment -------------------------------------------


def test_subprocess_runner_whitelists_the_environment(tmp_path) -> None:
    """``SubprocessRunner`` documents a whitelist; it must actually apply one.

    Its docstring claimed the environment "is *not* copied wholesale, mirroring
    the broker's whitelist rule", but no ``env=`` was passed — so ``curl``/``git``
    invocations launched through it inherited every declared secret. This is the
    no-broker fallback, so it is not the audited path, but a documented safety
    property that the code does not implement is worse than no claim at all.
    """
    import asyncio
    import json
    import os
    import sys

    from Sprout.skills.sources.cli import SubprocessRunner

    marker = "SPROUT_CLI_RUNNER_LEAK"
    original = os.environ.get(marker)
    os.environ[marker] = "sk-not-a-real-key"
    try:
        result = asyncio.run(
            SubprocessRunner().run(
                [
                    sys.executable,
                    "-c",
                    "import os, json; print(json.dumps({'secret': "
                    f"'{marker}' in os.environ, "
                    "'path': bool(os.environ.get('PATH'))}))",
                ]
            )
        )
    finally:
        if original is None:
            os.environ.pop(marker, None)
        else:
            os.environ[marker] = original

    payload = json.loads(result.stdout.strip())
    assert payload["secret"] is False, "the parent environment reached the child"
    assert payload["path"] is True, "the whitelist dropped PATH"

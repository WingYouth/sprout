"""SEC-10 regression: ``_run_command`` must not leak the parent environment.

Callers that omit ``env=`` used to inherit the whole parent environment, so an
unrelated API key sat one ``grep``/skill-script call away from a subprocess.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from Sprout.tools.system_tools import _run_command

_CHILD = (
    "import os, json;"
    "print(json.dumps({"
    "'secret': 'SPROUT_TEST_LEAK' in os.environ,"
    "'path': 'PATH' in os.environ"
    "}))"
)


async def test_run_command_strips_parent_secrets(monkeypatch):
    monkeypatch.setenv("SPROUT_TEST_LEAK", "leak-me")
    code, out, err = await _run_command(sys.executable, ["-c", _CHILD], timeout=20.0)
    assert code == 0, err
    payload = json.loads(out.strip())
    assert payload["secret"] is False
    assert payload["path"] is True


async def test_run_command_honours_explicit_env():
    code, out, _ = await _run_command(
        sys.executable,
        ["-c", "import os; print(os.environ.get('SPROUT_EXPLICIT', ''))"],
        env={"PATH": os.environ.get("PATH", ""), "SPROUT_EXPLICIT": "sent"},
        timeout=20.0,
    )
    assert code == 0
    assert out.strip() == "sent"


def test_git_env_keeps_a_path(monkeypatch: pytest.MonkeyPatch):
    """``git_env()`` with no argument is how every call site uses it.

    It forwarded ``base_env=None`` to ``SecretBroker.child_env``, which selects
    a whitelist *from* a source mapping — so ``None`` produced an environment
    holding just the five ``GIT_*`` pins and no ``PATH``. git survived only
    where the binary is found without one. The posture probe passes an explicit
    mapping, so it never exercised the shape production actually calls.
    """
    from Sprout.execution.git_env import GIT_ENV_PINS, git_env

    monkeypatch.setattr(os, "environ", {**os.environ, "PATH": "/usr/bin"})

    env = git_env()

    assert env.get("PATH") == "/usr/bin", "the child cannot find git without PATH"
    assert set(GIT_ENV_PINS) <= set(env), "the non-interactive pins were dropped"


def test_git_env_still_strips_secrets(monkeypatch: pytest.MonkeyPatch):
    """Adding the parent environment back must not add the secrets with it."""
    from Sprout.execution.git_env import git_env

    monkeypatch.setattr(
        os, "environ", {**os.environ, "PATH": "/usr/bin", "SPROUT_TEST_LEAK": "leak-me"}
    )

    env = git_env()

    assert "PATH" in env
    assert "SPROUT_TEST_LEAK" not in env


def test_git_env_honours_an_explicit_base(monkeypatch: pytest.MonkeyPatch):
    """The posture probe relies on passing its own mapping and seeing it filtered."""
    from Sprout.execution.git_env import git_env

    env = git_env({"PATH": "/x", "AWS_SECRET_ACCESS_KEY": "not-a-real-key"})

    assert env["PATH"] == "/x"
    assert "AWS_SECRET_ACCESS_KEY" not in env

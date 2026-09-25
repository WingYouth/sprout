"""What the sandbox's untrusted-code path is allowed to see.

``GitWorktreeSandbox.run_code`` is the one place in the runtime that executes
*untrusted* code: the model authors it, and a fetched skill or a repository's
contents can steer what it says. It spawns through :func:`run_capture`, which
passes ``env`` straight to ``create_subprocess_exec`` — and ``None`` there means
"inherit the parent environment".

Nothing passed it, so the child inherited everything, including every declared
secret (``DEEPSEEK_API_KEY`` and friends). Every other spawn point already
whitelists: ``ProcessBroker`` and ``CliRunTool`` through
``SecretBroker.child_env``, and the git helpers through ``git_env``.
"""

from __future__ import annotations

import asyncio
import sys

from Sprout.execution.models import SandboxRef
from Sprout.sandbox.git_worktree import GitWorktreeSandbox
from Sprout.workspace.models import Workspace, WorkspaceKind

#: Reads the marker and reports whether PATH survived, in one line.
_PROBE = (
    "import os, json;"
    "print(json.dumps({"
    "'secret': 'SPROUT_SANDBOX_LEAK' in os.environ,"
    "'path': bool(os.environ.get('PATH'))"
    "}))"
)


def _sandbox(tmp_path) -> GitWorktreeSandbox:
    """A sandbox whose ``run_code`` cwd exists; no git repo is needed for this."""
    workspace = Workspace(id="ws", root=tmp_path, kind=WorkspaceKind.LOCAL_DIRECTORY)
    return GitWorktreeSandbox(workspace)


def _ref(tmp_path) -> SandboxRef:
    return SandboxRef(id="s1", kind="git_worktree", root=tmp_path, worktree_ref=None)


def test_untrusted_code_does_not_inherit_secrets(tmp_path, monkeypatch) -> None:
    """A declared secret must not be readable from sandboxed code."""
    import json

    monkeypatch.setenv("SPROUT_SANDBOX_LEAK", "sk-a-real-looking-secret")

    output = asyncio.run(_sandbox(tmp_path).run_code(_ref(tmp_path), "python", _PROBE))

    assert json.loads(output.strip())["secret"] is False, (
        "sandboxed code could read the parent environment"
    )


def test_untrusted_code_still_gets_a_path(tmp_path) -> None:
    """Stripping the environment must not strip what a runtime needs to work.

    The whitelist keeps ``PATH`` (and the locale/temp variables a child needs);
    dropping it entirely would make the sandbox unable to start an interpreter
    on any platform where it is not an absolute path.
    """
    import json

    output = asyncio.run(_sandbox(tmp_path).run_code(_ref(tmp_path), "python", _PROBE))

    assert json.loads(output.strip())["path"] is True


def test_the_inline_interpreter_is_the_running_one(tmp_path) -> None:
    """``python`` must map to this interpreter, not a PATH lookup that may miss."""
    output = asyncio.run(
        _sandbox(tmp_path).run_code(_ref(tmp_path), "python", "import sys; print(sys.executable)")
    )

    assert output.strip() == sys.executable

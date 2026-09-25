"""Environment for runtime-spawned git helpers (AUTHZ §4.3).

``GitBroker``, ``ApplyBroker``, and ``GitWorktreeSandbox`` used to call
``create_subprocess_exec("git", ...)`` without an ``env=``, so git inherited the
whole parent environment — every declared secret included. That contradicted the
rule the rest of the execution layer follows (``ProcessBroker`` builds a
whitelist through :meth:`SecretBroker.child_env`, and ``CliRunTool`` documents
the same requirement), and it handed credentials to whatever program a
repository's own configuration names: ``core.pager``, ``core.fsmonitor``,
``diff.external``.

Two things happen here:

* the child gets the same **whitelist** every other runtime-spawned process
  gets, so an unrelated API key cannot leak into it;
* a handful of git knobs are pinned so a repository cannot make git execute a
  program on its behalf, and so git can never block waiting for a human.

Repository **hooks** are deliberately left enabled: they only exist if the
operator placed them there (``git clone`` does not copy hooks), and disabling
them would silently change what a commit does. OS-level isolation is the
container backend's job (AUTHZ §6.2).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from Sprout.security.secret_broker import SecretBroker

#: Environment variables that make a git invocation non-interactive. Without
#: them git can hang on a credential prompt (``GIT_TERMINAL_PROMPT``), page
#: output through an arbitrary program, or open an editor.
GIT_ENV_PINS: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "GIT_PAGER": "cat",
    "GIT_EDITOR": "true",
    "GIT_SEQUENCE_EDITOR": "true",
}

#: ``-c key=value`` arguments prepended to every invocation. Each one names a
#: program git would otherwise run on the repository's behalf. ``diff.external``
#: is *not* pinned here: ``-c diff.external=`` makes git try to spawn an empty
#: program name. Callers that diff pass ``--no-ext-diff`` instead.
GIT_CONFIG_PINS: tuple[str, ...] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.pager=cat",
)


def git_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """A whitelisted, non-interactive environment for one git child process.

    Defaults to the parent environment so the whitelist has something to filter.
    Passing ``base_env=None`` through to ``SecretBroker.child_env`` meant the
    child got ``{}`` — no ``PATH`` at all — because the whitelist selects *from*
    a source mapping rather than constructing one. git happened to keep working
    only where the executable is found without ``PATH`` (a system directory on
    Windows); on Linux/macOS, or any git installed elsewhere, the spawn fails.

    Callers may still pass an explicit mapping (the posture probe does, to check
    what gets filtered).
    """
    env = SecretBroker().child_env(
        base_env=os.environ if base_env is None else base_env
    )
    env.update(GIT_ENV_PINS)
    return env


def git_args(*args: str) -> tuple[str, ...]:
    """Prepend the hardened ``-c`` pins to a git argument list."""
    return (*GIT_CONFIG_PINS, *args)


__all__ = ["GIT_CONFIG_PINS", "GIT_ENV_PINS", "git_args", "git_env"]

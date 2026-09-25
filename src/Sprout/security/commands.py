"""Server-side command policy (AUTHZ §6.1).

``known_command`` used to travel in ``ActionRequest.arguments``, which let the
model attest to its own commands: any tool call could claim "this is a known
command" and skip approval. That flag is gone — the broker derives the facts from
this registry instead — but the *replacement* had a second problem: the default
allowlist was a list of general-purpose interpreters and build runners
(``python``, ``node``, ``npm``, ``uv``, ``make``, ``cargo``, ``mvn`` …), and
membership meant "runs without an approval". ``python -c "<anything>"`` was
therefore approved automatically.

Two questions are now separate fields:

``allowlist``
    Is ``argv[0]`` a name the operator is willing to see run? Derived
    server-side, never from the model — this is the self-attestation replacement.

``auto_run``
    Which of those may run **without an approval**?

``auto_run`` is empty by default, on purpose. Everything on a build-tool
allowlist executes code the *task itself* can write: ``pytest`` imports
``conftest.py`` from the working directory, ``npm test`` runs a script from
``package.json``, ``make`` runs whatever the Makefile says, ``cargo test``
compiles ``build.rs``. In worktree sandbox mode that directory is exactly where
the agent just wrote — the worktree is a logical boundary, not an OS one (AUTHZ
§6.2) — so auto-running any of them is equivalent to auto-running the agent's own
code. That is how the EVALUATION node became an unapproved route to host code
execution. Operators who accept the risk opt in per command in
``[security.commands] auto_run``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings

# Verification and build tooling only. Anything that can fetch and run
# arbitrary code (npx, bun, deno, sh, bash, cmd) stays out on purpose.
DEFAULT_COMMAND_ALLOWLIST: tuple[str, ...] = (
    "black",
    "cargo",
    "clang",
    "clang++",
    "cmake",
    "dotnet",
    "eslint",
    "flake8",
    "g++",
    "gcc",
    "git",
    "go",
    "gradle",
    "gradlew",
    "isort",
    "java",
    "javac",
    "make",
    "meson",
    "mvn",
    "mypy",
    "ninja",
    "node",
    "npm",
    "pnpm",
    "poetry",
    "prettier",
    "pyright",
    "pytest",
    "python",
    "python3",
    "ruff",
    "rustc",
    "swift",
    "tox",
    "tsc",
    "uv",
    "vitest",
    "yarn",
)

#: Commands that only *report* — they read the workspace and print, and cannot
#: execute code the task itself wrote. These may run under ``cli_tool_run``
#: without an approval.
#:
#: The design rule is narrow on purpose. A build tool is not read-only even
#: when it "just runs tests": ``pytest`` imports ``conftest.py`` from the
#: working directory, ``npm test`` runs a script from ``package.json``,
#: ``make`` does whatever the Makefile says. In worktree mode that directory is
#: exactly where the agent just wrote, so approving one of those on sight is
#: approving the agent's own code. Nothing that loads a file from the workspace
#: belongs in this set.
#:
#: Membership therefore means: the binary cannot be made to run anything from
#: the working directory by choosing arguments. ``git`` is the sharp edge — it
#: is one name for both ``git status`` and ``git commit`` — which is why the
#: read-only decision is made per *subcommand* in :func:`is_read_only_command`,
#: never by name alone.
READ_ONLY_COMMANDS: frozenset[str] = frozenset(
    {
        "cat",
        "date",
        "df",
        "dir",
        "du",
        "echo",
        "env",
        "file",
        "find",
        "grep",
        "head",
        "hostname",
        "id",
        "ls",
        "printenv",
        "pwd",
        "rg",
        "sort",
        "stat",
        "tail",
        "tree",
        "uname",
        "uniq",
        "wc",
        "where",
        "which",
        "whoami",
    }
)

#: ``git`` subcommands that only read. Anything absent — ``commit``, ``push``,
#: ``reset``, ``clean``, ``checkout``, ``config``, ``remote``, a bare ``git`` —
#: is not read-only. ``diff``/``log`` are included only because the callers pass
#: ``--no-ext-diff`` elsewhere; ``git diff`` can be made to run a program via
#: ``diff.external``, so it is deliberately *excluded* here.
READ_ONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "ls-files",
        "rev-parse",
        "show-ref",
        "branch",
        "describe",
        "shortlog",
        "blame",
        "grep",
        "cat-file",
        "show",
        "name-rev",
    }
)

#: Flags that turn an otherwise read-only command into an executor. ``find
#: -exec``/``-execdir``/``-delete``, ``rg --pre``, ``grep`` reading a FIFO —
#: these run programs or write. Rejecting the flag outright is cruder than
#: parsing each grammar, and cruder is the safer direction.
_EXECUTING_FLAGS: frozenset[str] = frozenset(
    {"-exec", "-execdir", "-ok", "-okdir", "-delete", "--pre", "--pre-glob", "-fexec"}
)


def is_read_only_command(argv: Sequence[str], *, registry: CommandRegistry) -> bool:
    """True when running ``argv`` cannot execute code or write to the workspace.

    Used to let ``cli_tool_run`` skip the approval prompt for commands an
    operator would otherwise be asked about repeatedly (``pwd``, ``git status``,
    ``ls``) while every command that *can* run workspace-authored code
    (``pytest``, ``npm``, ``make``, ``python``) keeps asking.
    """
    name = registry.name_of(argv)
    if not name or name in registry.denylist:
        return False
    # An explicit auto_run entry is the operator saying "I accept the risk for
    # this one" — that is the existing escape hatch and it still applies.
    if name in registry.auto_run:
        return True
    if any(str(part) in _EXECUTING_FLAGS for part in argv[1:]):
        return False
    if name == "git":
        return _git_subcommand_is_read_only(argv[1:])
    return name in READ_ONLY_COMMANDS


#: ``git`` options that consume the *next* argument. The subcommand is the first
#: argument that is neither one of these nor its value: ``git -C <path> status``
#: must read as ``status``, and taking the first non-``-`` token instead picks up
#: the path and would call every ``-C`` invocation non-read-only.
_GIT_OPTIONS_WITH_VALUES: frozenset[str] = frozenset(
    {"-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)

#: Options that set *git configuration* for the invocation. ``-c`` is not in the
#: list above because it does not merely take a value: it can set
#: ``core.fsmonitor``, ``diff.external`` or ``core.pager`` and make git run a
#: program of the caller's choosing. Any occurrence disqualifies the whole
#: invocation — there is no safe subcommand underneath ``-c``.
_GIT_CONFIG_INJECTING_OPTIONS: frozenset[str] = frozenset({"-c", "--config-env"})


def _git_subcommand_is_read_only(args: Sequence[str]) -> bool:
    """True when the ``git`` subcommand in ``args`` only reads."""
    # Configuration injection is checked across the whole argv *first*: git
    # accepts ``-c`` after the subcommand (``git status -c core.pager=cat``), so
    # scanning only up to the subcommand would let that form through. A single
    # occurrence disqualifies the invocation.
    for raw in args:
        part = str(raw)
        if part in _GIT_CONFIG_INJECTING_OPTIONS or part.startswith("-c"):
            return False

    skip_next = False
    for raw in args:
        part = str(raw)
        if skip_next:
            skip_next = False
            continue
        if part in _GIT_OPTIONS_WITH_VALUES:
            skip_next = True
            continue
        if part.startswith("-"):
            continue
        return part.casefold() in READ_ONLY_GIT_SUBCOMMANDS
    # No subcommand at all (bare ``git``, or only options): not read-only.
    return False

_WINDOWS_EXECUTABLE_SUFFIXES = frozenset({".bat", ".cmd", ".com", ".exe", ".ps1"})


@dataclass(frozen=True, slots=True)
class CommandRegistry:
    """Classifies a command line as acceptable, and as auto-runnable or not."""

    allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_COMMAND_ALLOWLIST)
    )
    denylist: frozenset[str] = frozenset()
    #: Commands that may run with **no approval**. Empty by default: see the
    #: module docstring for why an allowlist of build tools is not a safe
    #: auto-run list.
    auto_run: frozenset[str] = frozenset()

    @classmethod
    def from_settings(cls, security: SecuritySettings) -> CommandRegistry:
        """Build the registry from ``[security.commands]``, keeping the defaults."""
        commands = security.commands
        allowlist = (
            frozenset(commands.allowlist)
            if commands.allowlist
            else frozenset(DEFAULT_COMMAND_ALLOWLIST)
        )
        return cls(
            allowlist=allowlist,
            denylist=frozenset(commands.denylist),
            auto_run=frozenset(commands.auto_run),
        )

    @staticmethod
    def name_of(command: str | Sequence[str]) -> str:
        """Return the normalized ``argv[0]`` basename (``.exe``/``.cmd`` stripped)."""
        parts = command.split() if isinstance(command, str) else list(command)
        if not parts:
            return ""
        raw = str(parts[0]).strip().strip("\"'")
        name = PurePath(raw).name.casefold()
        for suffix in _WINDOWS_EXECUTABLE_SUFFIXES:
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    def is_allowlisted(self, command: str | Sequence[str]) -> bool:
        """A denylisted name always loses, even when it is also allowlisted."""
        name = self.name_of(command)
        if not name:
            return False
        if name in self.denylist:
            return False
        return name in self.allowlist

    def is_auto_runnable(self, command: str | Sequence[str]) -> bool:
        """True only for a name the operator explicitly lets run unapproved."""
        name = self.name_of(command)
        if not name:
            return False
        if name in self.denylist:
            return False
        return name in self.auto_run

    def class_key(self, command: str | Sequence[str]) -> str:
        """The name a "allow this whole class" grant may cover, or ``""``.

        An operator asked to approve ``sprout --help`` is being asked about one
        *invocation* but understands it as one *command*. Answering "yes, allow
        this class" therefore has to mean the name, or the next subcommand asks
        again — and a session of probing raises the prompt dozens of times.

        Widening to the name is only sound when the name cannot be turned into
        running code the agent itself just wrote. That excludes, deliberately:

        * the build-tool allowlist (``pytest``, ``make``, ``npm``, ``python``…),
          because each one loads a file from the working directory — in worktree
          mode that directory is where the task just wrote;
        * ``git``, which is one name for both ``git status`` and ``git push``;
        * anything denylisted, which must not gain a second route in;
        * names that already run unapproved (``auto_run``) or already skip the
          prompt (read-only), where a grant would add nothing.

        Everything left — ``sprout``, an operator's own tooling — is classed by
        name, and the caller is responsible for saying so in the prompt rather
        than promising a "class" it will not deliver.
        """
        name = self.name_of(command)
        if not name or name in self.denylist:
            return ""
        if name == "git" or name in self.auto_run:
            return ""
        if name in READ_ONLY_COMMANDS or name in self.allowlist:
            return ""
        return name

    def tag(self, command: str | Sequence[str]) -> dict[str, Any]:
        """Arguments the broker adds instead of trusting the model.

        ``allowlisted_command`` is provenance (the name was recognised);
        ``auto_run_command`` is what the policy matrix turns into ``ALLOW``. Only
        the second one may skip a human.
        """
        name = self.name_of(command)
        return {
            "command_name": name,
            "allowlisted_command": self.is_allowlisted(command),
            "auto_run_command": self.is_auto_runnable(command),
        }


def build_command_registry(security: SecuritySettings) -> CommandRegistry:
    """Convenience wrapper used by the runtime factory."""
    return CommandRegistry.from_settings(security)

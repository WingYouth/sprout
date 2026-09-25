"""Security posture self-check (AUTHZ_DESIGN.md §2, §5–§7).

An audit report describes the code on the day it was written. It cannot say
whether the boundary is still standing after the next refactor, and a fix that
nobody re-checks tends to rot without anyone noticing. This module turns the
2026-09-20 review (``.workbuddy/security-audit-*.md``) into checks that run
against the *effective* configuration and against the objects the runtime
actually builds, so "is the boundary still there" is a command rather than an
archaeology exercise.

Every finding names the review item it came from (``V1`` … ``V15``) and, just
as importantly, *how* it was reached:

``live``
    Evaluated against real objects — the command registry, the assembled
    layered policy engine, the SSRF guard, the git child environment. A green
    line here means the behaviour is present, not that a comment mentions it.
``structure``
    A source-level assertion or a signature inspection, used where no cheap
    runtime probe exists (a route calling its helper, a factory call site). It
    is honest but weaker: a rename can defeat it.
``residual``
    A limitation that was deliberately *not* fixed. Kept in the report so it
    cannot quietly turn into folklore.

Nothing here resolves DNS, opens a database, or writes to disk — the SSRF probe
injects its own resolver — so ``sprout security check`` is safe to run anywhere,
including on a production host.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.security.access import AccessDecision, ActionRequest, ActionType
from Sprout.security.approval import ApprovalManager
from Sprout.security.audit import SecurityAuditLog, verify_chain
from Sprout.security.commands import CommandRegistry
from Sprout.security.layer import SecurityLayer
from Sprout.security.layered_policy import LayeredPolicyEngine
from Sprout.security.net_guard import NetworkGuard
from Sprout.workspace.models import ResourceKind, ResourceRef

if TYPE_CHECKING:
    from Sprout.config.settings import Settings

#: Statuses, in increasing severity.
OK = "ok"
WARN = "warn"
RISK = "risk"

_SEVERITY = {OK: 0, WARN: 1, RISK: 2}

#: How a finding was reached.
LIVE = "live"
STRUCTURE = "structure"
RESIDUAL = "residual"

#: Reporting planes, in order.
ENTRY = "entry"
EXECUTION = "execution"
SANDBOX = "sandbox"
EVIDENCE = "evidence"

PLANES: tuple[tuple[str, str], ...] = (
    (ENTRY, "Entry surface"),
    (EXECUTION, "Execution authorisation"),
    (SANDBOX, "Network and subprocess"),
    (EVIDENCE, "Approvals, settings and audit"),
)

#: Commands that may run with no approval because the operator said so. Every
#: one of them executes code the task itself can write (AUTHZ §6.1), which is
#: why the default is empty and why a non-empty list is reported as a risk.
_AUTO_RUN_NOTE = (
    "Each of these executes code from the directory the task just wrote to "
    "(conftest.py, package.json scripts, Makefile targets), so it is an "
    "unapproved route to host code execution."
)

#: Representative commands for the process-approval probe. Every one of them is
#: a general-purpose entry point rather than a bounded verifier.
_PROBE_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-c", "print(1)"),
    ("node", "-e", "0"),
    ("pytest",),
    ("npm", "test"),
    ("make", "all"),
    ("uv", "run", "python", "-c", "print(1)"),
)

#: Broker entry points that must accept the owning task's ``DelegationScope``.
#: The policy engine denies anything outside a scope (``engine.py``), so a
#: broker that never receives one makes every channel-level narrowing vacuous
#: (audit item V5).
_SCOPE_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("Sprout.execution.process_broker", "ProcessBroker", "run"),
    ("Sprout.execution.file_broker", "FileBroker", "write_text"),
    ("Sprout.execution.file_broker", "FileBroker", "delete"),
    ("Sprout.execution.database_broker", "DatabaseBroker", "query"),
    ("Sprout.execution.database_broker", "DatabaseBroker", "execute"),
    ("Sprout.execution.git_broker", "GitBroker", "commit"),
    ("Sprout.execution.git_broker", "GitBroker", "push"),
    ("Sprout.execution.network_broker", "NetworkBroker", "get"),
    ("Sprout.execution.network_broker", "NetworkBroker", "post"),
    ("Sprout.execution.apply", "ApplyBroker", "apply"),
    ("Sprout.execution.apply", "ApplyBroker", "rollback"),
    ("Sprout.execution.sandbox_tool", "SandboxWriteTool", "__init__"),
)


def _is_loopback(host: str) -> bool:
    """True for the bind addresses that keep a surface on this machine only."""
    normalized = (host or "").strip().casefold()
    if not normalized:
        return False
    return normalized.startswith("127.") or normalized in {"localhost", "::1", "[::1]"}


def module_source(module_name: str) -> str | None:
    """Read a module's source from disk without importing it.

    ``find_spec`` imports the parent package but never the module itself, so a
    module that is heavy (``Sprout.runtime.factory``) or absent (``web.*`` on a
    library-only install) is handled without side effects. ``None`` means "could
    not be read here", which callers report as a warning rather than a pass.
    """
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    origin = getattr(spec, "origin", None)
    if not origin or not str(origin).endswith(".py"):
        return None
    try:
        return Path(str(origin)).read_text(encoding="utf-8")
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class PostureFinding:
    """One control, graded against the effective configuration."""

    ident: str
    title: str
    plane: str
    status: str
    basis: str
    detail: str
    remedy: str = ""

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.status, 0)

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.ident,
            "title": self.title,
            "plane": self.plane,
            "status": self.status,
            "basis": self.basis,
            "detail": self.detail,
            "remedy": self.remedy,
        }


@dataclass(frozen=True, slots=True)
class PostureReport:
    """Every finding, in reporting order."""

    findings: tuple[PostureFinding, ...] = ()
    config_path: str | None = None

    @property
    def risks(self) -> tuple[PostureFinding, ...]:
        return tuple(item for item in self.findings if item.status == RISK)

    @property
    def warnings(self) -> tuple[PostureFinding, ...]:
        return tuple(item for item in self.findings if item.status == WARN)

    @property
    def ok_count(self) -> int:
        return sum(1 for item in self.findings if item.status == OK)

    def status_code(self, *, strict: bool = False) -> int:
        """0 when nothing is open; 1 on a risk (or any warning with ``strict``)."""
        if self.risks:
            return 1
        if strict and self.warnings:
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable report.

        ``ok`` is the boolean status, matching the exit code and every other
        ``--json`` surface in this CLI (``storage check``, ``lanediag``): a
        consumer should be able to branch on it directly. It used to hold
        ``ok_count`` — an integer number of passing controls — under a key that
        means "did it pass" everywhere else, so ``payload["ok"] is True`` was
        False even on a clean run and the documented ``ok`` ↔ exit-code
        invariant did not hold. The count keeps its own name, and both are
        carried because the count is real information.
        """
        return {
            "config_path": self.config_path,
            "ok": not self.risks,
            "risks": len(self.risks),
            "warnings": len(self.warnings),
            "ok_count": self.ok_count,
            "findings": [item.to_dict() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class _Context:
    """Injectables, so tests can plant environment and fake module sources."""

    environ: Mapping[str, str]
    source: Callable[[str], str | None]


def _finding(
    ident: str,
    title: str,
    plane: str,
    status: str,
    basis: str,
    detail: str,
    remedy: str = "",
) -> PostureFinding:
    return PostureFinding(
        ident=ident,
        title=title,
        plane=plane,
        status=status,
        basis=basis,
        detail=detail,
        remedy=remedy,
    )


# -- entry surface ---------------------------------------------------------


def _web_auth(settings: Settings, ctx: _Context) -> PostureFinding:
    security = settings.security
    env_name = security.web_api_token_env
    token = ctx.environ.get(env_name, "")
    host = settings.web.host
    if security.web_auth_enabled and token:
        return _finding(
            "V1",
            "Web API authentication",
            ENTRY,
            OK,
            LIVE,
            f"A bearer token is required on every /api/* route ({env_name} is set); "
            "/api/health stays exempt so a probe still answers.",
        )
    if security.web_auth_enabled:
        return _finding(
            "V1",
            "Web API authentication",
            ENTRY,
            WARN,
            LIVE,
            f"web_auth_enabled=true but {env_name} is empty: every /api/* request is "
            "refused with 503. That fails closed, but it also shuts the console down.",
            f"export {env_name}=<token>, or set [security] web_auth_enabled=false to "
            "return to the loopback-only default.",
        )
    if _is_loopback(host):
        return _finding(
            "V1",
            "Web API authentication",
            ENTRY,
            WARN,
            LIVE,
            f"web_auth_enabled=false and the API binds {host}: the local-development "
            "default. Nothing off this machine can connect, and nothing on it needs "
            "a credential.",
            "Set [security] web_auth_enabled=true before binding to a LAN address, a "
            "container port map, or a reverse proxy.",
        )
    return _finding(
        "V1",
        "Web API authentication",
        ENTRY,
        RISK,
        LIVE,
        f"web_auth_enabled=false while web.host={host!r}: anyone who can reach that "
        "address can approve high-risk actions, apply change proposals, and open any "
        "path on this machine as a workspace.",
        f"Set [security] web_auth_enabled=true and export {env_name}.",
    )


def _feishu_callback(settings: Settings, ctx: _Context) -> PostureFinding:
    feishu = settings.feishu
    if not feishu.enabled:
        return _finding(
            "V4",
            "Feishu callback",
            ENTRY,
            OK,
            LIVE,
            "Feishu is disabled; /api/gateway/feishu/event is not registered.",
        )
    token = ctx.environ.get(feishu.verification_token_env, "")
    encrypt_key = ctx.environ.get(feishu.encrypt_key_env, "")
    if not token:
        return _finding(
            "V4",
            "Feishu callback",
            ENTRY,
            WARN,
            LIVE,
            f"Feishu is enabled but {feishu.verification_token_env} is empty. The "
            "callback route is not registered either, so nothing can be injected — "
            "but the channel is silently dead.",
            f"export {feishu.verification_token_env}=<token from the Feishu console>.",
        )
    if encrypt_key:
        return _finding(
            "V4",
            "Feishu callback",
            ENTRY,
            OK,
            LIVE,
            "Every callback must pass the verification-token check and, because an "
            "encrypt key is configured, the X-Lark-Signature check with its "
            "timestamp-replay window.",
        )
    return _finding(
        "V4",
        "Feishu callback",
        ENTRY,
        OK,
        LIVE,
        "Every callback must pass the verification-token check. No encrypt key is "
        f"configured, so X-Lark-Signature is not demanded ({feishu.encrypt_key_env} "
        "is unset).",
        f"Set {feishu.encrypt_key_env} to also require a signed request.",
    )


def _rpc_auth(settings: Settings, ctx: _Context) -> PostureFinding:
    security = settings.security
    env_name = security.rpc_api_token_env
    token = ctx.environ.get(env_name, "")
    if security.rpc_auth_enabled and token:
        return _finding(
            "V11",
            "RPC endpoint authentication",
            ENTRY,
            OK,
            LIVE,
            f"POST /api/rpc requires Authorization: Bearer <{env_name}>, compared in "
            "constant time.",
        )
    if security.rpc_auth_enabled:
        return _finding(
            "V11",
            "RPC endpoint authentication",
            ENTRY,
            WARN,
            LIVE,
            f"rpc_auth_enabled=true but {env_name} is empty: every RPC call is refused "
            "with 503. Fail-closed, but the endpoint is unusable.",
            f"export {env_name}=<token>, or set [security] rpc_auth_enabled=false.",
        )
    if security.web_auth_enabled:
        return _finding(
            "V11",
            "RPC endpoint authentication",
            ENTRY,
            OK,
            LIVE,
            "rpc_auth_enabled=false, but /api/rpc is not on the web exemption list, so "
            "it sits behind the web API token like every other /api/* route.",
        )
    return _finding(
        "V11",
        "RPC endpoint authentication",
        ENTRY,
        WARN,
        LIVE,
        "rpc_auth_enabled=false and the web API is unauthenticated: /api/rpc accepts "
        "anonymous JSON-RPC.",
        f"Set [security] rpc_auth_enabled=true and export {env_name}, or turn on web "
        "API authentication.",
    )


def _caller_identity(settings: Settings, ctx: _Context) -> PostureFinding:
    auth_source = ctx.source("web.webapi.auth")
    if auth_source is None:
        return _finding(
            "V12",
            "Caller identity",
            ENTRY,
            WARN,
            STRUCTURE,
            "The web package is not readable from here, so the identity helper could "
            "not be inspected.",
        )
    if "caller_user_id" not in auth_source:
        return _finding(
            "V12",
            "Caller identity",
            ENTRY,
            RISK,
            STRUCTURE,
            "web.webapi.auth no longer defines caller_user_id, so session and memory "
            "scoping would fall back to a value the caller supplies.",
            "Restore caller_user_id; identity must come from the entry-point adapter, "
            "never from the request body (AUTHZ §2.1).",
        )
    chat_source = ctx.source("web.webapi.routes.chat")
    uses_helper = chat_source is not None and "caller_user_id" in chat_source
    if not settings.security.web_auth_enabled:
        return _finding(
            "V12",
            "Caller identity",
            ENTRY,
            WARN,
            STRUCTURE,
            "Authentication is off, so caller_user_id returns the body's user_id (or "
            "'web-user'). On a loopback-only surface that is the documented default, "
            "but identity is then caller-supplied: naming someone else's user_id "
            "reaches their sessions and memory.",
            "Turn on [security] web_auth_enabled to pin identity server-side.",
        )
    if not uses_helper:
        return _finding(
            "V12",
            "Caller identity",
            ENTRY,
            RISK,
            STRUCTURE,
            "Authentication is on, but the chat route does not read caller_user_id, so "
            "an authenticated caller could still act as another user.",
            "Take the user_id from the authenticated principal in routes/chat.py.",
        )
    return _finding(
        "V12",
        "Caller identity",
        ENTRY,
        OK,
        STRUCTURE,
        "The chat route resolves its user_id through caller_user_id, and an "
        "authenticated principal wins over anything in the body.",
    )


# -- execution authorisation -----------------------------------------------


def _auto_run(settings: Settings) -> PostureFinding:
    registry = CommandRegistry.from_settings(settings.security)
    names = sorted(registry.auto_run)
    if not names:
        return _finding(
            "V2",
            "Unapproved command execution",
            EXECUTION,
            OK,
            LIVE,
            "The auto-run list is empty, so every process — including pytest, npm "
            "test, make and cargo — comes back as REQUIRE_APPROVAL. Being on the "
            "allowlist only says the name is recognisable.",
        )
    return _finding(
        "V2",
        "Unapproved command execution",
        EXECUTION,
        RISK,
        LIVE,
        "The operator opted these into running with no approval: "
        + ", ".join(names)
        + ". "
        + _AUTO_RUN_NOTE
        + " The hard floor still applies, but nothing else stands between the model "
        "and host code execution.",
        "Drop them from [security.commands] auto_run unless every repository this "
        "runtime opens is trusted.",
    )


def _process_approval(settings: Settings) -> PostureFinding:
    registry = CommandRegistry.from_settings(settings.security)
    engine = LayeredPolicyEngine.from_settings(settings.security)
    allowed: list[str] = []
    for command in _PROBE_COMMANDS:
        request = ActionRequest(
            action=ActionType.PROCESS_RUN,
            resource=ResourceRef(
                workspace_id="posture",
                path=".",
                kind=ResourceKind.CONFIG,
            ),
            arguments={"command": list(command), **registry.tag(command)},
        )
        if engine.decide(request).decision is AccessDecision.ALLOW:
            allowed.append(" ".join(command))
    if allowed:
        return _finding(
            "V3",
            "Evaluation commands ask for approval",
            EXECUTION,
            RISK,
            LIVE,
            "The real policy engine returns ALLOW for: "
            + ", ".join(allowed)
            + ". "
            + _AUTO_RUN_NOTE,
            "Remove those names from [security.commands] auto_run.",
        )
    return _finding(
        "V3",
        "Evaluation commands ask for approval",
        EXECUTION,
        OK,
        LIVE,
        f"All {len(_PROBE_COMMANDS)} representative commands (python -c, node -e, "
        "pytest, npm test, make, uv run) are REQUIRE_APPROVAL when the policy engine "
        "is asked directly — so a regression that made engine.py trust a "
        "caller-supplied flag would show up here.",
    )


def _delegation_scope() -> PostureFinding:
    import importlib

    missing: list[str] = []
    for module_name, class_name, method_name in _SCOPE_TARGETS:
        label = f"{class_name}.{method_name}"
        try:
            module = importlib.import_module(module_name)
            target = getattr(getattr(module, class_name), method_name)
            parameters = inspect.signature(target).parameters
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            missing.append(f"{label} ({type(exc).__name__})")
            continue
        if "scope" not in parameters:
            missing.append(label)
    if missing:
        return _finding(
            "V5",
            "Delegation scope reaches the brokers",
            EXECUTION,
            RISK,
            STRUCTURE,
            "These entry points no longer accept a scope: "
            + ", ".join(missing)
            + ". A broker that hard-codes an empty scope makes the engine's "
            "'outside DelegationScope' rule vacuous, so channel-level read-only "
            "grants stop narrowing anything.",
            "Thread the owning task's DelegationScope down to the broker, as "
            "Runtime.run_task_process does.",
        )
    return _finding(
        "V5",
        "Delegation scope reaches the brokers",
        EXECUTION,
        OK,
        STRUCTURE,
        f"All {len(_SCOPE_TARGETS)} broker entry points accept the owning task's "
        "DelegationScope, which is what gives the engine's scope rule something to "
        "deny.",
    )


def _tool_risk(settings: Settings, ctx: _Context) -> PostureFinding:
    def unresolvable(name: str) -> str:
        raise LookupError(name)

    layer = SecurityLayer.from_settings(settings.security, tool_risk_lookup=unresolvable)
    request = ActionRequest(
        action=ActionType.FILE_READ,
        resource=ResourceRef(
            workspace_id="posture",
            path="notes.txt",
            kind=ResourceKind.PUBLIC,
        ),
        arguments={"tool_name": "posture-no-such-tool"},
    )
    denies_unknown = layer.policy_engine.decide(request).decision is AccessDecision.DENY
    if not denies_unknown:
        return _finding(
            "V6",
            "Tool-risk floor",
            EXECUTION,
            RISK,
            LIVE,
            "A read attributed to a tool the registry cannot resolve came back "
            "anything but DENY, so the risk layer is not consulting the server-side "
            "lookup.",
            "Wire LayeredPolicyEngine's tool_risk_lookup to the tool registry; an "
            "unresolvable tool must fail closed.",
        )
    source = ctx.source("Sprout.runtime.factory")
    if source is None:
        return _finding(
            "V6",
            "Tool-risk floor",
            EXECUTION,
            WARN,
            LIVE,
            "The engine denies an unresolvable tool, but Sprout.runtime.factory could "
            "not be read, so the wiring that hands it the registry lookup is "
            "unverified.",
        )
    if "tool_risk_lookup=tool_risk_lookup" not in source:
        return _finding(
            "V6",
            "Tool-risk floor",
            EXECUTION,
            RISK,
            STRUCTURE,
            "runtime/factory.py no longer passes tool_risk_lookup to SecurityLayer, so "
            "the risk floor is dead in the running runtime even though the engine "
            "supports it.",
            "Pass tool_risk_lookup when assembling SecurityLayer in factory.py.",
        )
    return _finding(
        "V6",
        "Tool-risk floor",
        EXECUTION,
        OK,
        LIVE,
        "The engine denies a tool the lookup cannot resolve (fail-closed), and "
        "runtime/factory.py hands it a closure over the tool registry, so the level "
        "never comes from the caller's arguments.",
    )


# -- network and subprocess ------------------------------------------------


def _ssrf_guard() -> PostureFinding:
    private = NetworkGuard(resolver=lambda host: ("10.0.0.5",))
    public = NetworkGuard(resolver=lambda host: ("93.184.216.34",))
    problems: list[str] = []
    if private.check("http://looks-public.example/").allowed:
        problems.append("a target that resolves inside the private ranges was allowed")
    if not public.check("http://example.com/").allowed:
        problems.append("a globally routable target was refused")
    if NetworkGuard().check("http://metadata.google.internal/").allowed:
        problems.append("the cloud-metadata hostname was allowed")
    if NetworkGuard().check("file:///etc/passwd").allowed:
        problems.append("a non-HTTP scheme was allowed")
    guard = NetworkGuard()
    if not 0 < guard.dns_ttl_seconds < float("inf"):
        problems.append("the DNS cache has no TTL, so one poisoned answer lasts forever")
    if guard.dns_cache_max <= 0:
        problems.append("the DNS cache is unbounded")
    if problems:
        return _finding(
            "V7",
            "Outbound SSRF guard",
            SANDBOX,
            RISK,
            LIVE,
            "The guard let through something it must refuse: " + "; ".join(problems) + ".",
            "Restore the private-range and metadata-host refusals — network.get is "
            "ALLOW in the matrix, so this guard is the only thing standing there.",
        )
    return _finding(
        "V7",
        "Outbound SSRF guard",
        SANDBOX,
        OK,
        LIVE,
        "A verdict on a privately-resolving target, a metadata hostname and a "
        "non-HTTP scheme all come back refused, while a globally routable target is "
        "allowed; the DNS cache is bounded and expires.",
    )


def _dns_rebinding() -> PostureFinding:
    return _finding(
        "V7b",
        "DNS rebinding",
        SANDBOX,
        WARN,
        RESIDUAL,
        "The verdict is computed from one resolution while the HTTP client performs "
        "its own, so a TTL-0 record that answers with a public address first and a "
        "loopback address second can still slip past the guard.",
        "Pinning the connection to the verified address needs a custom transport; "
        "until then, keep a proxy in front of outbound requests (AUTHZ §6.3).",
    )


def _git_child_env() -> PostureFinding:
    from Sprout.execution.git_env import GIT_CONFIG_PINS, GIT_ENV_PINS, git_env

    planted = {
        "PATH": os.environ.get("PATH", ""),
        "AWS_SECRET_ACCESS_KEY": "posture-probe-not-a-real-key",
        "SPROUT_POSTURE_PROBE": "posture-probe-not-a-real-key",
    }
    env = git_env(planted)
    problems: list[str] = []
    leaked = sorted(name for name in planted if name != "PATH" and name in env)
    if leaked:
        problems.append("parent variables reached the child: " + ", ".join(leaked))
    unpinned = sorted(set(GIT_ENV_PINS) - set(env))
    if unpinned:
        problems.append("non-interactive pins are missing: " + ", ".join(unpinned))
    if "core.fsmonitor=false" not in GIT_CONFIG_PINS:
        problems.append(
            "core.fsmonitor is not pinned, so a repository can name a program for "
            "git to run"
        )
    if problems:
        return _finding(
            "V8",
            "git child environment",
            SANDBOX,
            RISK,
            LIVE,
            "git helpers no longer get the whitelisted environment the rest of the "
            "execution plane uses: " + "; ".join(problems) + ".",
            "Route every git invocation through execution/git_env.py.",
        )
    return _finding(
        "V8",
        "git child environment",
        SANDBOX,
        OK,
        LIVE,
        "A planted API key and an unrelated variable are both stripped from the git "
        "child environment, the non-interactive pins are present, and fsmonitor and "
        "pager are overridden so a repository cannot make git run something.",
    )


def _git_hooks() -> PostureFinding:
    return _finding(
        "V8b",
        "git hooks",
        SANDBOX,
        WARN,
        RESIDUAL,
        "Repository hooks stay enabled on purpose: they only exist if the operator "
        "put them there, and disabling them would silently change what a commit "
        "does. A repository whose hooks are malicious therefore still runs them.",
        "Accept, or run repository operations inside the container backend "
        "(AUTHZ §6.2) where the hooks are isolated.",
    )


# -- approvals, settings and audit -----------------------------------------


def _approval_subject(settings: Settings, ctx: _Context) -> PostureFinding:
    source = ctx.source("web.webapi.routes.approvals")
    if source is None:
        return _finding(
            "V13",
            "Who may approve",
            EVIDENCE,
            WARN,
            STRUCTURE,
            "The web approval route could not be read, so the recorded decider could "
            "not be inspected.",
        )
    if "caller_user_id" not in source:
        return _finding(
            "V13",
            "Who may approve",
            EVIDENCE,
            RISK,
            STRUCTURE,
            "The web decision route no longer derives decided_by from the authenticated "
            "caller, so the audit trail would name whoever the body says.",
            "Take decided_by from the principal in routes/approvals.py.",
        )
    return _finding(
        "V13",
        "Who may approve",
        EVIDENCE,
        OK,
        STRUCTURE,
        "The web decision route records decided_by from the authenticated caller, not "
        "from the body. MCP remains request-only: it can raise a proposal but never "
        "grant one.",
    )


def _one_shot_approvals(settings: Settings) -> PostureFinding:
    security = settings.security
    if not security.require_approval:
        return _finding(
            "V9",
            "One-shot approvals",
            EVIDENCE,
            RISK,
            LIVE,
            "security.require_approval=false: nothing is ever put in front of a human, "
            "so the whole decision surface is off regardless of the matrix.",
            "Set [security] require_approval=true.",
        )
    if not hasattr(ApprovalManager, "_consume_lock"):
        return _finding(
            "V9",
            "One-shot approvals",
            EVIDENCE,
            RISK,
            STRUCTURE,
            "Consuming a single-use grant is a read-modify-write again with no "
            "per-record lock, so two concurrent callers can both spend the same grant "
            "(and the same approval_used_once audit entry becomes a lie).",
            "Restore the per-record lock in ApprovalManager.is_approved.",
        )
    unattended = security.approvals.unattended
    notes = ""
    status = OK
    remedy = ""
    if unattended != "deny":
        status = WARN
        notes = (
            f" Unattended tasks use {unattended!r} rather than 'deny', so a cron or "
            "channel task can obtain a grant no human ever saw."
        )
        remedy = 'Set [security.approvals] unattended="deny" to refuse that outright.'
    return _finding(
        "V9",
        "One-shot approvals",
        EVIDENCE,
        status,
        STRUCTURE,
        "Single-use grants are consumed inside a per-record lock, so only one "
        "concurrent caller wins; approvals still require a human "
        "(require_approval=true)." + notes,
        remedy,
    )


def _settings_masking(settings: Settings, ctx: _Context) -> PostureFinding:
    from Sprout.config.loader import mask_settings

    # Plant a credential in a DSN and run the production helper over a copy of
    # the real settings: this asks the masking code itself, rather than asking
    # whether some pattern is still spelled the way it used to be.
    planted = "posture-probe-password"
    probe = copy.deepcopy(settings)
    probe.storage.cache = f"redis://user:{planted}@127.0.0.1:6379/0"
    rendered = json.dumps(mask_settings(probe), default=str)
    if planted in rendered:
        return _finding(
            "V10",
            "Settings exposure",
            EVIDENCE,
            RISK,
            LIVE,
            "mask_settings let a planted DSN password through, so GET /api/settings "
            "would hand out storage credentials.",
            "Restore the credential patterns in security/redact.py.",
        )
    source = ctx.source("web.webapi.routes.settings")
    if source is None:
        return _finding(
            "V10",
            "Settings exposure",
            EVIDENCE,
            WARN,
            LIVE,
            "A planted DSN password is masked, but the settings route could not be "
            "read, so whether it serves the masked view is unverified.",
        )
    if "mask_settings" not in source:
        return _finding(
            "V10",
            "Settings exposure",
            EVIDENCE,
            RISK,
            STRUCTURE,
            "The settings route no longer calls mask_settings, so GET /api/settings "
            "hands out the effective config: DSN passwords, the command allow and deny "
            "lists, the SSRF exemptions and the audit path.",
            "Serve mask_settings(effective) from routes/settings.py.",
        )
    exposure = ""
    if not settings.security.web_auth_enabled:
        exposure = (
            " The endpoint is still reachable without a credential while web auth is "
            "off; the mask is what limits the damage."
        )
    return _finding(
        "V10",
        "Settings exposure",
        EVIDENCE,
        OK,
        LIVE,
        "mask_settings stripped a planted DSN password from the effective config, and "
        "GET /api/settings serves that masked view." + exposure,
    )


def _audit_chain(settings: Settings) -> PostureFinding:
    log = SecurityAuditLog.from_settings(settings.security)
    if not log.enabled:
        return _finding(
            "V14",
            "Audit stream",
            EVIDENCE,
            WARN,
            LIVE,
            "security.audit.enabled=false: authorization decisions leave no trace at "
            "all.",
            "Set [security.audit] enabled=true.",
        )
    path = Path(log.path)
    if not path.exists():
        return _finding(
            "V14",
            "Audit stream",
            EVIDENCE,
            OK,
            LIVE,
            f"Enabled; no stream has been written yet at {log.path}.",
        )
    result = verify_chain(path)
    if not result.ok:
        if result.foreign:
            lines = ", ".join(str(index) for index in result.foreign[:5])
            return _finding(
                "V14",
                "Audit stream",
                EVIDENCE,
                RISK,
                LIVE,
                f"{len(result.foreign)} line(s) at {log.path} are not audit entries "
                f"(line {lines}); the {result.checked} chained entries hash correctly.",
                "A line that is not an entry did not break the chain — the entries "
                "themselves verify. Establish what wrote it and remove it; until "
                "then the stream is not fully accounted for.",
            )
        return _finding(
            "V14",
            "Audit stream",
            EVIDENCE,
            RISK,
            LIVE,
            f"The hash chain breaks at entry {result.broken_at}: {result.reason}.",
            "Treat the stream as suspect until the cause is known — a broken link "
            "means an edit, a reorder or a dropped line.",
        )
    return _finding(
        "V14",
        "Audit stream",
        EVIDENCE,
        OK,
        LIVE,
        f"The hash chain verifies across {result.checked} entries at {log.path}.",
    )


def _audit_key() -> PostureFinding:
    return _finding(
        "V14b",
        "Audit chain keying",
        EVIDENCE,
        WARN,
        RESIDUAL,
        "The chain is unkeyed SHA-256, so it proves that entries were not edited "
        "carelessly — it cannot stop someone who may write the file from recomputing "
        "the whole chain. Concurrent appends are serialised by a file lock, so a "
        "second writer no longer forks the chain.",
        "Switching to HMAC is a format change and needs a key-management decision "
        "(where the key lives, how it rotates), so it stays open by design.",
    )


def assess_posture(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    source_reader: Callable[[str], str | None] | None = None,
    config_path: str | None = None,
) -> PostureReport:
    """Grade every authorization control against the effective settings.

    ``environ`` and ``source_reader`` exist so tests can plant a token or fake a
    module source without touching the machine's real environment.
    """
    ctx = _Context(
        environ=dict(os.environ if environ is None else environ),
        source=source_reader or module_source,
    )
    findings = (
        _web_auth(settings, ctx),
        _feishu_callback(settings, ctx),
        _rpc_auth(settings, ctx),
        _caller_identity(settings, ctx),
        _auto_run(settings),
        _process_approval(settings),
        _delegation_scope(),
        _tool_risk(settings, ctx),
        _ssrf_guard(),
        _dns_rebinding(),
        _git_child_env(),
        _git_hooks(),
        _approval_subject(settings, ctx),
        _one_shot_approvals(settings),
        _settings_masking(settings, ctx),
        _audit_chain(settings),
        _audit_key(),
    )
    return PostureReport(findings=findings, config_path=config_path)


__all__ = [
    "EVIDENCE",
    "ENTRY",
    "EXECUTION",
    "LIVE",
    "OK",
    "PLANES",
    "RESIDUAL",
    "RISK",
    "SANDBOX",
    "STRUCTURE",
    "WARN",
    "PostureFinding",
    "PostureReport",
    "assess_posture",
    "module_source",
]

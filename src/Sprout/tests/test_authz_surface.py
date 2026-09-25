"""Structural guard for the authorization plane (AUTHZ_DESIGN.md).

Why this exists
---------------
A silently dropped edit leaves no behavioural trace: the module still imports,
the suite still passes, and nothing notices that the new field, method or import
never made it to disk. Two real examples from this change: ``plane.py`` lost its
``classify_overrides`` field (only surfaced when the runtime touched it) and
``scanner.py`` lost the ``field`` import (only surfaced as a NameError at import
time).

Three layers cover the whole failure class, and all three belong in the suite:

1. importing the package      -> catches jammed syntax and dropped imports
2. ``ruff --select F``        -> catches undefined names / unused imports
3. this module                -> catches a dropped member that no other test
                                 happens to exercise

Layer 3 is the one that needs hand-written assertions, because only the author
knows what the change promised to expose.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

# (module, symbol, attributes that must exist on the symbol)
SURFACE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # --- A1 hard floor + the unified policy contract ---------------------
    ("Sprout.security.floor", "HardFloor", ("check",)),
    ("Sprout.security.floor", "DEFAULT_FLOOR_RULES", ()),
    ("Sprout.security.protocol", "PolicyEngineProtocol", ("decide",)),
    # --- A2 command allowlist (replaces known_command self-attestation) --
    (
        "Sprout.security.commands",
        "CommandRegistry",
        (
            "from_settings",
            "name_of",
            "is_allowlisted",
            "is_auto_runnable",
            "tag",
            "allowlist",
            "denylist",
            "auto_run",
        ),
    ),
    # --- A3 secrets + one redactor ---------------------------------------
    ("Sprout.security.redact", "Redactor", ("redact", "redact_mapping")),
    ("Sprout.security.redact", "RedactionResult", ("text", "count")),
    ("Sprout.security.secret_broker", "SecretBroker", ("child_env", "inject_env", "redact")),
    ("Sprout.security.secrets", "SecretProvider", ("get", "list_names")),
    ("Sprout.security.secrets", "EnvSecretProvider", ("get", "list_names")),
    # --- A4 SSRF guard ----------------------------------------------------
    ("Sprout.security.net_guard", "NetworkGuard", ("check", "acheck")),
    # --- A5 audit ---------------------------------------------------------
    (
        "Sprout.security.audit",
        "SecurityAuditLog",
        ("record", "record_decision", "verify", "report", "tail"),
    ),
    ("Sprout.security.audit", "verify_chain", ()),
    # --- approvals --------------------------------------------------------
    (
        "Sprout.security.approval",
        "ApprovalManager",
        ("request", "decide", "sweep_expired", "oldest_pending_age", "suggest_allowlist", "store"),
    ),
    ("Sprout.security.approval", "ApprovalPolicy", ("from_settings", "unattended")),
    ("Sprout.security.approval", "ApprovalMode", ()),
    ("Sprout.security.approval", "ApprovalStatus", ()),
    # --- policy engines ---------------------------------------------------
    ("Sprout.security.engine", "PolicyEngine", ("decide", "floor")),
    (
        "Sprout.security.layered_policy",
        "LayeredPolicyEngine",
        ("decide", "from_settings", "floor", "layers"),
    ),
    ("Sprout.security.layered_policy", "PolicyRule", ("id", "action", "path_glob", "decision")),
    ("Sprout.security.layered_policy", "PolicyLayer", ("from_mapping", "from_command_globs")),
    ("Sprout.security.policy", "SecurityPolicy", ("evaluate", "decide_for_spec", "check")),
    ("Sprout.security.access", "PolicyDecision", ("decision", "matched_rules", "approval_id")),
    ("Sprout.security.access", "ActionRequest", ()),
    ("Sprout.security.access", "ActionType", ()),
    # --- the single assembly object --------------------------------------
    ("Sprout.security.layer", "SecurityLayer", ("from_settings", "describe")),
    # --- classification shared by read/write/scanner ---------------------
    ("Sprout.workspace.classifier", "classify", ()),
    ("Sprout.workspace.classifier", "classify_with_reason", ()),
    ("Sprout.workspace.classifier", "ResourceClassifier", ("classify",)),
    ("Sprout.workspace.classifier", "DEFAULT_CLASSIFY_RULES", ()),
    ("Sprout.workspace.read_broker", "ReadBroker", ("read", "redactor")),
    # --- identity no longer trusts the message body ----------------------
    ("Sprout.gateway.identity", "Principal", ("authenticated", "source", "is_service")),
    ("Sprout.gateway.identity", "service_principal", ()),
    ("Sprout.gateway.identity", "principal_from_message", ()),
    ("Sprout.gateway.identity", "discarded_roles", ()),
    # --- delegation scope -------------------------------------------------
    (
        "Sprout.task.models",
        "DelegationScope",
        ("expires_at", "max_depth", "issued_by", "is_expired", "narrow"),
    ),
    ("Sprout.task.models", "coerce_source", ()),
    ("Sprout.task.models", "UNATTENDED_SOURCES", ()),
    # --- trajectory path-injection guard ---------------------------------
    ("Sprout.trajectory.recorder", "safe_trajectory_name", ()),
    ("Sprout.trajectory.recorder", "trajectory_path", ()),
    # --- execution results carry the new provenance fields ---------------
    ("Sprout.execution.models", "ProcessResult", ("allowlisted", "redactions")),
    ("Sprout.execution.models", "FileResult", ("resource_kind",)),
    ("Sprout.execution.models", "NetworkResult", ("redactions",)),
    # --- runtime wiring ---------------------------------------------------
    (
        "Sprout.runtime.runtime",
        "Runtime",
        (
            "approvals",
            "audit",
            "decide_approval",
            "pending_approvals",
            "sweep_approvals",
            "approval_backlog_age",
        ),
    ),
    # --- CLI surfaces -----------------------------------------------------
    ("Sprout.cli.commands.approvals", "app", ()),
    ("Sprout.cli.commands.audit", "app", ()),
    ("Sprout.cli.commands.security", "app", ()),
    # --- the posture self-check -------------------------------------------
    ("Sprout.security.posture", "assess_posture", ()),
    (
        "Sprout.security.posture",
        "PostureReport",
        ("risks", "warnings", "ok_count", "status_code", "to_dict"),
    ),
    (
        "Sprout.security.posture",
        "PostureFinding",
        ("ident", "status", "basis", "severity", "to_dict"),
    ),
    # --- web entry-point authentication (AUTHZ §2.1) ----------------------
    (
        "web.webapi.auth",
        "WebAuth",
        ("from_settings", "is_exempt", "rejection", "principal_for"),
    ),
    ("web.webapi.auth", "WebAuthMiddleware", ()),
    ("web.webapi.auth", "caller_user_id", ()),
    ("web.webapi.auth", "warn_if_exposed", ()),
)


def _identity(case: tuple[str, str, tuple[str, ...]]) -> str:
    module, symbol, _ = case
    return f"{module.split('.')[-1]}:{symbol}"


@pytest.mark.parametrize(
    ("module_name", "symbol", "attrs"),
    SURFACE,
    ids=[_identity(case) for case in SURFACE],
)
def test_public_api_surface_is_intact(
    module_name: str, symbol: str, attrs: tuple[str, ...]
) -> None:
    module = importlib.import_module(module_name)
    assert hasattr(module, symbol), f"{module_name} no longer exports {symbol!r}"
    target = getattr(module, symbol)
    missing = [name for name in attrs if not hasattr(target, name)]
    assert not missing, f"{module_name}.{symbol} is missing {missing}"


def test_security_layer_carries_classify_overrides() -> None:
    """Instance-level check: a no-default dataclass field is invisible on the class."""
    from Sprout.security.layer import SecurityLayer

    fields = set(getattr(SecurityLayer, "__dataclass_fields__", {}))
    assert "classify_overrides" in fields, (
        "SecurityLayer.classify_overrides went missing; the read broker, file "
        "broker and scanner all read it, so [security.classify] would silently "
        "stop applying."
    )


def test_audit_log_instance_exposes_its_path() -> None:
    from Sprout.security.audit import SecurityAuditLog

    log = SecurityAuditLog(Path("x.jsonl"))
    for name in ("path", "enabled", "failures", "fallback_path"):
        assert hasattr(log, name), f"SecurityAuditLog instance is missing {name!r}"


def test_package_exports_resolve() -> None:
    """Every name in ``Sprout.security.__all__`` must actually exist."""
    from Sprout.security import __all__ as exported

    module = importlib.import_module("Sprout.security")
    missing = [name for name in exported if not hasattr(module, name)]
    assert not missing, f"Sprout.security.__all__ exports missing names: {missing}"


def test_every_module_all_resolves() -> None:
    """Repo-wide: a module that exports a name it does not define is broken."""
    root = Path(__file__).resolve().parents[2]
    broken: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "__pycache__", "build", "dist"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        defined: set[str] = set()
        exported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == "__all__" for target in node.targets
            ):
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                    exported += [
                        element.value
                        for element in value.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)
                    ]
        missing = [name for name in exported if name not in defined]
        if missing:
            broken.append(f"{path.relative_to(root)}: {missing}")
    assert not broken, "modules export undefined names:\n" + "\n".join(broken)

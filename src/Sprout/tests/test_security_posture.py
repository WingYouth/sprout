"""``sprout security check`` — the posture checks must be load-bearing.

The 2026-09-20 review left thirteen fixes behind. A fix nobody re-checks rots,
so this module does two things for every control worth guarding:

1. it pins the *passing* state, so a rename or a dropped parameter is noticed;
2. it removes the guard and pins the *failing* state, so a check that would say
   "ok" no matter what cannot pass for a check (the project's ablation rule:
   take the guard away and the test protecting it must go red).

Everything here builds its own ``Settings`` and points the audit stream at
``tmp_path``: the real ``~/.sprout`` is never opened or written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from Sprout.cli.app import app
from Sprout.config.settings import Settings
from Sprout.security.audit import SecurityAuditLog
from Sprout.security.layered_policy import LayeredPolicyEngine
from Sprout.security.net_guard import NetworkGuard, NetworkVerdict
from Sprout.security.posture import (
    OK,
    RESIDUAL,
    RISK,
    WARN,
    assess_posture,
)

#: Every control the report is expected to cover, in reporting order. A control
#: that silently disappears from the report is as bad as one that turns red.
EXPECTED_IDS: tuple[str, ...] = (
    "V1",
    "V4",
    "V11",
    "V12",
    "V2",
    "V3",
    "V5",
    "V6",
    "V7",
    "V7b",
    "V8",
    "V8b",
    "V13",
    "V9",
    "V10",
    "V14",
    "V14b",
)

#: Broker entry points whose ``scope`` parameter is the whole reason channel
#: narrowing works (audit item V5). Pinned by name so shortening the list of
#: targets cannot silently turn the check into a no-op.
EXPECTED_SCOPE_TARGETS: frozenset[str] = frozenset(
    {
        "ProcessBroker.run",
        "FileBroker.write_text",
        "FileBroker.delete",
        "DatabaseBroker.query",
        "DatabaseBroker.execute",
        "GitBroker.commit",
        "GitBroker.push",
        "NetworkBroker.get",
        "NetworkBroker.post",
        "ApplyBroker.apply",
        "ApplyBroker.rollback",
        "SandboxWriteTool.__init__",
    }
)


def _settings(tmp_path: Path, **security: object) -> Settings:
    """Default settings with the audit stream moved into ``tmp_path``."""
    settings = Settings()
    settings.security.audit.path = str(tmp_path / "audit" / "security.jsonl")
    for key, value in security.items():
        setattr(settings.security, key, value)
    return settings


def _find(report, ident: str):
    matches = [item for item in report.findings if item.ident == ident]
    assert matches, f"no finding for {ident}; report covers {[i.ident for i in report.findings]}"
    assert len(matches) == 1, f"{ident} is reported more than once"
    return matches[0]


def test_report_covers_every_control(tmp_path: Path) -> None:
    report = assess_posture(_settings(tmp_path))
    assert tuple(item.ident for item in report.findings) == EXPECTED_IDS


def test_residuals_are_labelled_and_not_counted_as_ok(tmp_path: Path) -> None:
    report = assess_posture(_settings(tmp_path))
    residuals = [item for item in report.findings if item.basis == RESIDUAL]
    assert {item.ident for item in residuals} == {"V7b", "V8b", "V14b"}
    assert all(item.status == WARN for item in residuals)


def test_a_default_configuration_has_no_open_control(tmp_path: Path) -> None:
    """The shipped defaults must come back clean, or the check cries wolf."""
    report = assess_posture(_settings(tmp_path))
    assert report.risks == (), [item.detail for item in report.risks]
    assert report.status_code() == 0
    assert report.status_code(strict=True) == 1  # residuals still warn


# -- entry surface ---------------------------------------------------------


def test_a_public_bind_without_authentication_is_a_risk(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.web.host = "0.0.0.0"
    finding = _find(assess_posture(settings), "V1")
    assert finding.status == RISK
    assert "web_auth_enabled" in finding.remedy
    assert assess_posture(settings).status_code() == 1


def test_enabling_web_auth_without_a_token_warns_fail_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path, web_auth_enabled=True)
    report = assess_posture(settings, environ={})
    finding = _find(report, "V1")
    assert finding.status == WARN
    assert "503" in finding.detail
    assert "SPROUT_WEB_TOKEN" in finding.detail


def test_a_configured_token_turns_web_authentication_ok(tmp_path: Path) -> None:
    settings = _settings(tmp_path, web_auth_enabled=True)
    report = assess_posture(settings, environ={"SPROUT_WEB_TOKEN": "s3cret"})
    assert _find(report, "V1").status == OK
    # /api/rpc is not on the exemption list, so it inherits that token.
    assert _find(report, "V11").status == OK


def test_rpc_authentication_reports_the_fail_closed_case(tmp_path: Path) -> None:
    settings = _settings(tmp_path, rpc_auth_enabled=True)
    finding = _find(assess_posture(settings, environ={}), "V11")
    assert finding.status == WARN
    assert "503" in finding.detail


def test_feishu_without_a_verification_token_is_never_silently_open(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.feishu.enabled = True
    finding = _find(assess_posture(settings, environ={}), "V4")
    assert finding.status == WARN
    assert "not registered" in finding.detail


def test_caller_identity_needs_the_authenticated_principal(tmp_path: Path) -> None:
    sources = {
        "web.webapi.auth": "def caller_user_id(request): ...",
        "web.webapi.routes.chat": "user_id=caller_user_id(request)",
    }
    settings = _settings(tmp_path, web_auth_enabled=True)
    environ = {"SPROUT_WEB_TOKEN": "t"}
    ok = _find(
        assess_posture(settings, environ=environ, source_reader=sources.get), "V12"
    )
    assert ok.status == OK

    # Ablation: the route stops using the helper it was given.
    detached = dict(sources, **{"web.webapi.routes.chat": "user_id=body['user_id']"})
    broken = _find(
        assess_posture(settings, environ=environ, source_reader=detached.get), "V12"
    )
    assert broken.status == RISK

    # Ablation: identity is off entirely, so the body decides who you are.
    unauthenticated = _find(
        assess_posture(_settings(tmp_path), source_reader=sources.get), "V12"
    )
    assert unauthenticated.status == WARN
    assert "user_id" in unauthenticated.detail


# -- execution authorisation -----------------------------------------------


def test_auto_run_reopens_unapproved_execution(tmp_path: Path) -> None:
    clean = _find(assess_posture(_settings(tmp_path)), "V2")
    assert clean.status == OK

    settings = _settings(tmp_path)
    settings.security.commands.auto_run = ("pytest",)
    report = assess_posture(settings)
    opted_in = _find(report, "V2")
    assert opted_in.status == RISK
    assert "pytest" in opted_in.detail
    # The engine probe sees the same thing, so a change to engine.py that
    # trusted a caller flag would be caught even with an empty auto_run.
    probe = _find(report, "V3")
    assert probe.status == RISK
    assert "pytest" in probe.detail
    assert report.status_code() == 1


def test_the_allowlist_alone_does_not_grant_a_process(tmp_path: Path) -> None:
    """Being recognisable is not permission: the probe is what pins that."""
    finding = _find(assess_posture(_settings(tmp_path)), "V3")
    assert finding.status == OK
    assert "REQUIRE_APPROVAL" in finding.detail


def test_scope_targets_cover_every_broker_entry_point() -> None:
    from Sprout.security.posture import _SCOPE_TARGETS

    covered = frozenset(f"{cls}.{method}" for _, cls, method in _SCOPE_TARGETS)
    assert covered == EXPECTED_SCOPE_TARGETS


def test_delegation_scope_reaches_the_brokers(tmp_path: Path) -> None:
    finding = _find(assess_posture(_settings(tmp_path)), "V5")
    assert finding.status == OK
    assert "12" in finding.detail


def test_tool_risk_floor_denies_an_unresolvable_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _find(assess_posture(_settings(tmp_path)), "V6").status == OK

    # Ablation: the risk layer stops running, which is what a dropped
    # tool_risk_lookup or a reverted _risk_check would look like.
    monkeypatch.setattr(
        LayeredPolicyEngine, "_risk_check", lambda self, request: None
    )
    assert _find(assess_posture(_settings(tmp_path)), "V6").status == RISK


def test_tool_risk_floor_reports_an_unwired_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reader(name: str) -> str | None:
        if name == "Sprout.runtime.factory":
            return "security = SecurityLayer.from_settings(settings.security)"
        return None

    finding = _find(
        assess_posture(_settings(tmp_path), source_reader=reader), "V6"
    )
    assert finding.status == RISK
    assert "factory" in finding.detail


# -- network and subprocess ------------------------------------------------


def test_ssrf_guard_refuses_private_and_metadata_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _find(assess_posture(_settings(tmp_path)), "V7").status == OK

    # Ablation: a guard that answers "allowed" to everything must be reported.
    monkeypatch.setattr(
        NetworkGuard, "check", lambda self, url: NetworkVerdict(True, "ablation")
    )
    assert _find(assess_posture(_settings(tmp_path)), "V7").status == RISK


def test_git_child_environment_drops_parent_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _find(assess_posture(_settings(tmp_path)), "V8").status == OK

    # Ablation: pass the parent environment straight through, which is exactly
    # what the three git call sites did before execution/git_env.py existed.
    import Sprout.execution.git_env as git_env_module

    monkeypatch.setattr(
        git_env_module, "git_env", lambda base_env=None: dict(base_env or {})
    )
    finding = _find(assess_posture(_settings(tmp_path)), "V8")
    assert finding.status == RISK
    assert "reached the child" in finding.detail


def test_git_env_pins_are_still_present(tmp_path: Path) -> None:
    from Sprout.execution.git_env import GIT_CONFIG_PINS, GIT_ENV_PINS

    assert "core.fsmonitor=false" in GIT_CONFIG_PINS
    assert GIT_ENV_PINS["GIT_TERMINAL_PROMPT"] == "0"
    assert _find(assess_posture(_settings(tmp_path)), "V8").status == OK


# -- approvals, settings and audit -----------------------------------------


def test_closing_the_approval_surface_is_a_risk(tmp_path: Path) -> None:
    settings = _settings(tmp_path, require_approval=False)
    finding = _find(assess_posture(settings), "V9")
    assert finding.status == RISK
    assert "require_approval" in finding.remedy


def test_a_loose_unattended_policy_warns(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.security.approvals.unattended = "sandbox_only"
    finding = _find(assess_posture(settings), "V9")
    assert finding.status == WARN
    assert "sandbox_only" in finding.detail


def test_settings_route_must_serve_the_masked_view(tmp_path: Path) -> None:
    sources = {"web.webapi.routes.settings": '"settings": mask_settings(effective)'}
    assert (
        _find(
            assess_posture(_settings(tmp_path), source_reader=sources.get), "V10"
        ).status
        == OK
    )

    # Ablation: back to dump_settings, which leaked DSN passwords.
    ablated = {"web.webapi.routes.settings": '"settings": dump_settings(effective)'}
    finding = _find(
        assess_posture(_settings(tmp_path), source_reader=ablated.get), "V10"
    )
    assert finding.status == RISK
    assert "mask_settings" in finding.remedy


def test_a_broken_audit_chain_is_a_risk(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "security.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    log = SecurityAuditLog(path)
    log.record("policy.decision", {"actor": "tester", "decision": "allow"})

    settings = _settings(tmp_path)
    settings.security.audit.path = str(path)
    assert _find(assess_posture(settings), "V14").status == OK

    # Tamper: edit the recorded decision without recomputing the hash.
    tampered = path.read_text(encoding="utf-8").replace('"allow"', '"deny"')
    path.write_text(tampered, encoding="utf-8")
    finding = _find(assess_posture(settings), "V14")
    assert finding.status == RISK
    assert "hash" in finding.detail.lower()


def test_disabled_audit_is_reported(tmp_path: Path) -> None:
    settings = _settings(tmp_path, require_approval=True)
    settings.security.audit.enabled = False
    assert _find(assess_posture(settings), "V14").status == WARN


# -- CLI -------------------------------------------------------------------


def _config(tmp_path: Path, *, auto_run: str = "") -> Path:
    config = tmp_path / "sprout.toml"
    config.write_text(
        "[security.commands]\n"
        f"auto_run = [{auto_run}]\n"
        "\n"
        "[security.audit]\n"
        f'path = "{(tmp_path / "audit" / "security.jsonl").as_posix()}"\n',
        encoding="utf-8",
    )
    return config


def test_cli_reports_json_and_exits_zero_on_a_clean_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["security", "check", "--json", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["risks"] == 0
    assert [item["id"] for item in payload["findings"]] == list(EXPECTED_IDS)


def test_json_ok_is_a_boolean_matching_the_exit_code(tmp_path: Path) -> None:
    """``ok`` is status everywhere else in this CLI; it must be here too.

    It held the *count* of passing controls instead, so ``payload["ok"] is
    True`` was False even on a clean run and the documented "``ok`` agrees with
    the exit code" invariant did not hold. The count is real data, so it keeps
    its own key.
    """
    result = CliRunner().invoke(
        app, ["security", "check", "--json", "--config", str(_config(tmp_path))]
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True, "a clean report must read as ok"
    assert payload["ok"] is (result.exit_code == 0)
    # The count is controls in the OK state specifically — a warning is neither
    # a risk nor a pass, so it is counted in neither bucket.
    assert payload["ok_count"] == sum(
        1 for item in payload["findings"] if item["status"] == "ok"
    )
    assert payload["ok_count"] == 11


def test_json_ok_is_false_when_a_control_is_open(tmp_path: Path) -> None:
    config = _config(tmp_path, auto_run='"pytest"')
    result = CliRunner().invoke(
        app, ["security", "check", "--json", "--config", str(config)]
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["ok"] is (result.exit_code == 0), "ok and the exit code disagree"


def test_cli_exits_one_when_a_control_is_open(tmp_path: Path) -> None:
    config = _config(tmp_path, auto_run='"pytest"')
    result = CliRunner().invoke(
        app, ["security", "check", "--json", "--config", str(config)]
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["risks"] >= 1
    assert "V2" in [item["id"] for item in payload["findings"] if item["status"] == RISK]


def test_cli_strict_fails_on_a_residual_only_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result = CliRunner().invoke(
        app, ["security", "check", "--strict", "--config", str(config)]
    )
    assert result.exit_code == 1


def test_cli_renders_the_human_report(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["security", "check", "--config", str(_config(tmp_path))]
    )
    assert result.exit_code == 0
    assert "Authorization posture" in result.stdout
    assert "V8" in result.stdout
    assert "No control is open" in result.stdout

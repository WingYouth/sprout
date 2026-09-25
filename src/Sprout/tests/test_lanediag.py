"""Guardrails for the database lifecycle, now a pair of CLI commands:
``sprout storage init`` (create) and ``sprout storage check`` (prove).

Deliberately offline: an authority-only configuration exercises both verbs
without needing Redis/Milvus/Neo4j. The parts that actually matter for the
Docker stack — the verbs are registered, the module entry point the container
relies on works, and the generated ``~/.sprout/docker/six_lane_*.py`` scripts hold no second copy of
the logic — are asserted directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner

from Sprout.cli.app import app
from Sprout.config.loader import load_settings
from Sprout.storage import lanediag

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = REPO_ROOT / "src" / "Sprout" / "config" / "docker_templates"

# Mirrors the shipped no-Docker profile: authority lanes plus a context lane so a
# fan-out exists, and no service anywhere.
LAPTOP_TOML = (
    "[storage]\n"
    'operational = "sqlite:///data/sprout_audit.db"\n'
    'knowledge = "sqlite:///data/sprout_knowledge.db"\n'
    'metadata = "sqlite:///data/sprout_core.db"\n'
    'session = "sqlite:///data/sprout_conversation.db"\n'
    'context = "sqlite:///data/context.db"\n'
    'cache = "memory"\n'
    'vectors = "memory"\n'
    'graph = "none"\n'
    'blobs_dir = "data/sprout_blobs"\n'
    'trajectory_dir = "data/sprout_trajectory"\n'
    "\n"
    "[storage.observations]\n"
    "enabled = true\n"
    'dsn = "sqlite:///data/sprout_audit.db"\n'
)

OFFLINE_TOML = LAPTOP_TOML.replace(
    'context = "sqlite:///data/context.db"\n',
    'context = "none"\n',
)

SERVICE_LANES = {"Redis (hot path)", "Milvus (vectors)", "Neo4j (graph)"}


def _laptop_profile(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPROUT_CONFIG", raising=False)
    config = tmp_path / "sprout.toml"
    config.write_text(LAPTOP_TOML, encoding="utf-8")
    return config


@pytest.fixture()
def offline(tmp_path, monkeypatch):
    """Authority-only settings: no derived lanes, so no services are needed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPROUT_CONFIG", raising=False)
    config = tmp_path / "sprout.toml"
    config.write_text(OFFLINE_TOML, encoding="utf-8")
    monkeypatch.setenv("SPROUT_CONFIG", str(config))
    settings = load_settings(config)
    # Premise check, so the tests below cannot pass for the wrong reason.
    assert settings.storage.cache == "memory"
    assert settings.storage.vectors == "memory"
    assert settings.storage.graph == "none"
    return settings


# -- check ------------------------------------------------------------------


def test_check_reports_nothing_to_prove(offline) -> None:
    """No derived lanes means status 2 and an explanation, not a traceback."""
    report = asyncio.run(lanediag.check_lanes(offline))
    assert report.status == lanediag.STATUS_NO_FANOUT
    assert report.lanes == []
    assert any("fan-out" in note for note in report.notes)
    assert ("session", str(offline.storage.session)) in report.context


def test_cli_check_is_registered_and_forwards_the_status(offline) -> None:
    """A missing/broken registration would not print the banner at all."""
    result = CliRunner().invoke(app, ["storage", "check"])
    assert result.exit_code == lanediag.STATUS_NO_FANOUT
    assert "Six-lane check" in result.stdout
    assert "fan-out" in result.stdout
    # Exit 2 must read as "nothing to prove", not as a failure: a laptop
    # profile without derived lanes is a legitimate configuration.
    assert "Nothing to prove" in result.stdout
    assert "failed" not in result.stdout


def test_cli_check_emits_json(offline) -> None:
    result = CliRunner().invoke(app, ["storage", "check", "--json"])
    assert result.exit_code == lanediag.STATUS_NO_FANOUT
    payload = json.loads(result.stdout)
    assert payload["status"] == lanediag.STATUS_NO_FANOUT
    assert payload["lanes"] == []
    assert payload["ok"] is False


def test_cli_check_json_stays_parseable_with_real_lanes(tmp_path, monkeypatch) -> None:
    """The regression the zero-lane fixture above cannot see.

    With no lanes there is nothing to report on, so the per-lane progress
    callback never fires and stdout is trivially clean. A profile that *has*
    lanes prints ``healthy  <lane>`` from inside ``check_lanes`` — before the
    ``--json`` branch is reached — which put six lines ahead of the document and
    made ``storage check --json`` unparseable for every real deployment.
    """
    config = _laptop_profile(tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["storage", "check", "--json", "--config", str(config)])

    assert result.stdout.lstrip().startswith("{"), (
        "human-readable progress leaked into the JSON payload:\n" + result.stdout[:300]
    )
    payload = json.loads(result.stdout)
    assert payload["lanes"], "the fixture was expected to have lanes to print"
    # The invariant behind TC-4.4: `ok` and the exit code never disagree.
    assert payload["ok"] is (result.exit_code == lanediag.STATUS_OK)


def test_cli_init_narrates_its_phases(tmp_path, monkeypatch) -> None:
    """``ui.muted`` formats a string; it does not print one.

    Every progress line in ``storage init`` was a bare ``ui.muted(...)``
    statement, so the ``[n/4]`` narration the plan asks for was discarded and
    the command appeared to start at the lane table.
    """
    config = _laptop_profile(tmp_path, monkeypatch)

    result = CliRunner().invoke(app, ["storage", "init", "--config", str(config), "--no-chmod"])

    assert "[4/4]" in result.stdout, result.stdout[:400]


def test_cli_init_json_stays_parseable(tmp_path, monkeypatch) -> None:
    """Narrating the phases must not spill into the machine-readable output."""
    config = _laptop_profile(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        app, ["storage", "init", "--json", "--config", str(config), "--no-chmod"]
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == result.exit_code


def test_laptop_profile_verifies_files_and_skips_service_lanes(tmp_path, monkeypatch) -> None:
    """A lane on an in-process backend must be *skipped*, never claimed as verified.

    Regression guard for a real crash: while the check was Docker-only it built a
    ``MilvusClient`` unconditionally and died with ``uri: memory is illegal`` the
    first time it ran against this profile.
    """
    config = _laptop_profile(tmp_path, monkeypatch)
    report = asyncio.run(lanediag.check_lanes(load_settings(config)))

    assert report.status == lanediag.STATUS_OK
    verified = [lane.name for lane in report.lanes]
    assert "SQLite (authority)" in verified
    assert "BlobStore (objects)" in verified
    # The four lanes with no external backend are named as skipped, and they are
    # not also reported as passing lanes.
    assert set(report.skipped) == SERVICE_LANES | {"JSONL (evidence)"}
    assert not set(report.skipped) & set(verified)
    assert all(lane.ok for lane in report.lanes)


# -- init -------------------------------------------------------------------


def test_cli_init_creates_the_authority_lanes(tmp_path, monkeypatch) -> None:
    """`init` is the sibling verb of `check`; it must actually create the stores."""
    config = _laptop_profile(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["storage", "init", "--config", str(config)])

    assert result.exit_code == 0, result.stdout
    assert "SQLite (authority)" in result.stdout
    assert "databases," in result.stdout
    assert "BlobStore (objects)" in result.stdout

    # The five SQLite databases exist and carry their schema (not empty files).
    for name in (
        "sprout_conversation",
        "sprout_audit",
        "sprout_knowledge",
        "sprout_core",
    ):
        assert (tmp_path / "data" / f"{name}.db").exists(), f"{name}.db was not created"
    with sqlite3.connect(tmp_path / "data" / "sprout_conversation.db") as conn:
        tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    assert tables >= 3, "init left sprout_conversation.db without its schema"
    assert (tmp_path / "data" / "sprout_blobs").is_dir()


def test_cli_init_skips_lanes_with_no_backend_to_create(tmp_path, monkeypatch) -> None:
    """A service lane must not be claimed as created when it is not configured."""
    config = _laptop_profile(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["storage", "init", "--config", str(config)])

    assert result.exit_code == 0, result.stdout
    for lane in SERVICE_LANES:
        assert f"skipped {lane}" in result.stdout, f"{lane} was not reported skipped"


def test_init_is_idempotent(tmp_path, monkeypatch) -> None:
    """Running it twice must not fail: every step is IF NOT EXISTS."""
    config = _laptop_profile(tmp_path, monkeypatch)
    runner = CliRunner()
    first = runner.invoke(app, ["storage", "init", "--config", str(config)])
    second = runner.invoke(app, ["storage", "init", "--config", str(config)])
    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout


# -- wiring -----------------------------------------------------------------


def test_report_renders_every_lane() -> None:
    report = lanediag.LaneReport(title="T")
    report.add("a", "wrote-a", "saw-a", True)
    report.add("b", "wrote-b", "saw-b", False)
    rendered = report.plain()
    assert "[  ok] a" in rendered
    assert "[FAIL] b" in rendered
    assert report.ok is False


def test_module_entry_point_exposes_storage(tmp_path) -> None:
    """``python -m Sprout`` is how the runner image reaches the CLI.

    The image never installs the package (source is a read-only bind mount, so
    there is no ``sprout`` executable on PATH); if this entry point breaks, the
    whole Docker database lifecycle breaks with it.

    Deliberately Temporal-independent: ``main()`` runs a Temporal startup hook
    before every command (see ``test_main_keeps_the_boot_hooks_inside_the_redirect``),
    so driving ``-m Sprout`` here would require a live server and hang on a
    laptop without one. This test only asserts the entry point imports and the
    CLI exposes ``storage``; it bypasses that hook and pins
    ``TEMPORAL_AUTO_START=false`` so no dev server is spawned.
    """
    env = os.environ.copy()
    env.pop("SPROUT_CONFIG", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["TEMPORAL_AUTO_START"] = "false"
    proc = subprocess.run(
        [sys.executable, "-m", "Sprout", "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "storage" in proc.stdout


def test_docker_scripts_are_only_shims() -> None:
    """Each verb must exist once. Re-inlining one would break this."""
    for name, expected in (
        ("six_lane_probe.py", "from Sprout.storage.lanediag import check_lanes"),
        ("six_lane_init.py", "from Sprout.storage.lanediag import init_lanes"),
    ):
        source = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert expected in source, f"{name} no longer delegates to the package"
        for duplicated in ("sqlite3", "MilvusClient", "GraphDatabase"):
            assert duplicated not in source, f"{duplicated} re-inlined into {name}"


def test_stack_verbs_invoke_the_cli_commands() -> None:
    """The stack has to invoke the verbs, not the old script paths."""
    compose = (TEMPLATE_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "- sprout-redis-data:/data" in compose
    assert "- sprout-neo4j-data:/data" in compose
    assert "  sprout-redis-data:" in compose
    assert "  sprout-neo4j-data:" in compose
    dockerfile = (TEMPLATE_DIR / "Dockerfile.app").read_text(encoding="utf-8")
    ps1 = (TEMPLATE_DIR / "bootstrap.ps1").read_text(encoding="utf-8")
    sh = (TEMPLATE_DIR / "bootstrap.sh").read_text(encoding="utf-8")

    check_verb = '["python", "-m", "Sprout", "storage", "check"]'
    assert check_verb in compose
    assert check_verb in dockerfile
    # ... and the init verb reaches the sibling CLI command.
    assert '"storage", "init"' in ps1
    assert "Sprout storage init" in sh

    for text in (compose, dockerfile, ps1, sh):
        assert "six_lane_probe.py" not in text


# -- autostart does not fight an already-running stack ----------------------


def test_a_listening_lane_is_not_brought_up_again() -> None:
    """``up`` must be skipped for a lane that already answers.

    Observed 2026-09-24: ``sprout chat`` died with
    ``RuntimeError: Docker storage startup failed`` on a machine whose redis,
    milvus and neo4j containers were healthy and up for three days. The
    generated compose file pinned ``container_name`` while the bootstrap passes
    a fixed ``--project-name``, so compose tried to create ``/sprout-neo4j`` a
    second time and exited non-zero on the name conflict. Nothing was wrong with
    the containers; the ``up`` simply had no reason to run.

    The template no longer pins ``container_name`` (that is the root fix), but
    the probe stays: it is what keeps a running stack from being touched at all.
    """
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    mp = pytest.MonkeyPatch()
    mp.setattr(bootstrap, "_port_is_open", lambda dsn, **kw: True)
    try:
        assert bootstrap._services_needing_start(settings) == []
    finally:
        mp.undo()


def test_a_silent_lane_is_still_brought_up() -> None:
    """The cold machine still gets its stack: this is the half that must not regress."""
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    mp = pytest.MonkeyPatch()
    mp.setattr(bootstrap, "_port_is_open", lambda dsn, **kw: False)
    try:
        assert bootstrap._services_needing_start(settings) == [
            "sprout-redis",
            "sprout-milvus",
            "sprout-neo4j",
        ]
    finally:
        mp.undo()


def test_autostart_skips_compose_when_every_lane_listens() -> None:
    """With all lanes answering, no ``docker compose`` process is spawned at all."""
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202 - stub for subprocess.run
        calls.append(list(command))

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    mp = pytest.MonkeyPatch()
    mp.setattr(bootstrap, "_port_is_open", lambda dsn, **kw: True)
    mp.setattr(bootstrap.subprocess, "run", fake_run)
    try:
        asyncio.run(bootstrap._start_local_services(settings))
    finally:
        mp.undo()
    assert calls == [], f"compose was spawned for a running stack: {calls}"


def test_every_configured_lane_has_a_dsn_to_probe() -> None:
    """The probe needs a host:port per lane; a DSN without one reads as "down"."""
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    local = bootstrap._local_dsns(settings)
    assert set(local) == {"redis", "milvus", "neo4j"}
    for kind, dsn in local.items():
        parsed = urlsplit(dsn)
        assert parsed.hostname, f"{kind} DSN has no host"
        assert parsed.port, f"{kind} DSN has no port, so it can never be probed"


def _local_stack_settings():
    """Settings pointing all three external lanes at this machine."""
    from Sprout.config.settings import Settings, StorageSettings

    return Settings(
        storage=StorageSettings(
            cache="redis://127.0.0.1:6380/0",
            vectors="milvus://127.0.0.1:19530",
            graph="neo4j://neo4j:sprout123@localhost:7687",
        )
    )


def test_port_probe_reports_a_closed_port_as_down() -> None:
    """A port nothing listens on is "down" — the probe must not assume success."""
    from Sprout.storage import bootstrap

    # Port 1 on loopback is not a service; a refused connect means "needs start".
    assert bootstrap._port_is_open("redis://127.0.0.1:1/0", timeout=0.2) is False


def test_the_lane_stack_does_not_pin_container_names() -> None:
    """``container_name`` is what made two compose projects fight.

    A pinned ``container_name`` ignores ``--project-name``, so a stack brought
    up from a directory (project ``docker``) and one brought up by the bootstrap
    (project ``sprout``) both claim ``/sprout-neo4j`` — the second start dies on
    the name conflict. Without the pin, each project qualifies its own names and
    they coexist. In-network DNS uses *service* names, which do not change, so
    ``sprout-redis:6379`` and friends keep resolving.
    """
    compose = (TEMPLATE_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "container_name" not in compose, (
        "a pinned container_name re-introduces the two-project collision"
    )
    # The service names the rest of the code addresses must survive.
    for service in ("sprout-redis", "sprout-neo4j", "sprout-milvus"):
        assert f"  {service}:" in compose, f"service {service} disappeared"


def test_a_stopped_container_is_adopted_not_replaced() -> None:
    """A stopped container is started, not recreated — its volumes hold the data.

    A stack from an earlier revision keeps redis keys and the neo4j graph in
    *anonymous* volumes that the current compose file never names. Letting
    ``up`` create a parallel container leaves that data on an orphan, which is
    silent and unrecoverable from the new stack's point of view.
    """
    from Sprout.storage import bootstrap

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202 - stub for subprocess.run
        calls.append(list(command))

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    mp = pytest.MonkeyPatch()
    mp.setattr(bootstrap.subprocess, "run", fake_run)
    try:
        assert bootstrap._start_existing_container("docker", "sprout-redis") is True
        # ...and a name that does not exist reports "nothing to adopt".
        assert calls[0][:3] == ["docker", "start", "sprout-redis"]
    finally:
        mp.undo()


def test_adoption_is_skipped_when_the_container_does_not_exist() -> None:
    """No container by that name → compose creates one, as on a cold machine."""
    from Sprout.storage import bootstrap

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202 - stub for subprocess.run
        class _Done:
            returncode = 1  # `docker start` on a missing container
            stdout = ""
            stderr = "No such container"

        return _Done()

    mp = pytest.MonkeyPatch()
    mp.setattr(bootstrap.subprocess, "run", fake_run)
    try:
        assert bootstrap._start_existing_container("docker", "sprout-redis") is False
    finally:
        mp.undo()


def test_a_stopped_lane_is_adopted_instead_of_up_ed() -> None:
    """The wiring, not just the helper: a stopped lane must never reach ``up``.

    ``test_a_stopped_container_is_adopted_not_replaced`` proves the helper
    works; it would still pass if ``_start_local_services`` never called it,
    which is exactly the bug that orphaned data. This drives the whole function
    and asserts on what it ultimately shells out to.
    """
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202 - stub for subprocess.run
        commands.append(list(command))

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    def fake_which(name):  # noqa: ANN001, ANN202 - stub for shutil.which
        return "docker"

    mp = pytest.MonkeyPatch()
    # Ports are closed (the stopped case), but the containers exist.
    mp.setattr(bootstrap, "_port_is_open", lambda dsn, **kw: False)
    mp.setattr(bootstrap, "_await_listening", lambda dsn, **kw: None)
    mp.setattr(bootstrap.subprocess, "run", fake_run)
    mp.setattr(bootstrap.shutil, "which", fake_which)
    try:
        asyncio.run(bootstrap._start_local_services(settings))
    finally:
        mp.undo()

    started = [c[2] for c in commands if len(c) > 2 and c[:2] == ["docker", "start"]]
    assert sorted(started) == ["sprout-milvus", "sprout-neo4j", "sprout-redis"], (
        f"stopped lanes were not adopted: docker start saw {started}"
    )
    assert not any("compose" in c for c in commands), (
        f"compose ran even though every lane was adopted: {commands}"
    )


def test_every_adopted_lane_has_a_dsn_to_wait_on() -> None:
    """Adopting skips compose's healthcheck, so each adopted lane needs a wait target."""
    from Sprout.storage import bootstrap

    settings = _local_stack_settings()
    by_service = {
        bootstrap._SERVICE_NAMES[kind]: dsn
        for kind, dsn in bootstrap._local_dsns(settings).items()
    }
    for service in ("sprout-redis", "sprout-neo4j", "sprout-milvus"):
        assert service in by_service, f"{service} has no DSN, so a wait cannot be issued"

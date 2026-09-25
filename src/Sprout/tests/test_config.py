"""Configuration tests: defaults, deep merge, TOML loading, and error handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from Sprout.config import loader
from Sprout.config.defaults import default_settings
from Sprout.config.loader import dump_settings, load_settings, settings_from_dict
from Sprout.config.settings import MCPClientSettings
from Sprout.config.sprout_home import ensure_sprout_home, sprout_home

# Defaults live under the per-user sprout home (``~/.sprout/data``) since the
# data-home migration, so the expected values are computed here instead of being
# hard-coded: an absolute path in an assertion only passes on one machine.
_HOME_DATA = sprout_home() / "data"


def _home_dsn(name: str) -> str:
    """Build the SQLite DSN the defaults resolve to for a file in ``~/.sprout/data``."""
    return f"sqlite:///{(_HOME_DATA / name).as_posix()}"


# -- defaults ---------------------------------------------------------------------


def test_default_settings_require_model_configuration() -> None:
    settings = default_settings()
    assert settings.model.provider == "aiyallm"
    assert settings.model.model == ""
    assert settings.storage.operational == _home_dsn("sprout_audit.db")
    assert settings.storage.knowledge == _home_dsn("sprout_knowledge.db")
    assert settings.storage.observations.dsn == _home_dsn("sprout_audit.db")
    assert settings.storage.session == _home_dsn("sprout_conversation.db")
    assert settings.storage.usage == _home_dsn("sprout_usage.db")
    assert settings.storage.project_root == (_HOME_DATA / "projects").as_posix()
    assert settings.mcp.clients == ()


def test_default_settings_stay_inside_the_sprout_home() -> None:
    """The data-home migration must not leave a relative ``data/`` path behind."""
    settings = default_settings()
    home = sprout_home().as_posix()
    for value in (
        settings.storage.operational,
        settings.storage.knowledge,
        settings.storage.metadata,
        settings.storage.session,
        settings.storage.observations.dsn,
        settings.storage.blobs_dir,
        settings.storage.trajectory_dir,
    ):
        assert home in str(value), f"{value!r} points outside {home}"
        assert not str(value).startswith("sqlite:///data/"), f"{value!r} still uses the old layout"


def test_sprout_home_bootstrap_creates_minimal_accurate_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    ensure_sprout_home()

    home = tmp_path / ".sprout"
    expected_dirs = {
        "data",
        "data/audit",
        "data/context",
        "data/memory",
        "data/sprout_blobs",
        "data/sprout_trajectory",
        "data/projects",
        "skills",
        "docker",
    }
    for relative in expected_dirs:
        assert (home / relative).is_dir(), f"{relative} was not created"

    for stale in (
        "docker/volumes/sqlite",
        "docker/volumes/jsonl",
        "docker/volumes/blob",
        "docker/volumes/redis",
        "docker/volumes/neo4j",
    ):
        assert not (home / stale).exists(), f"{stale} should not be created"

    config = (home / "sprout.toml").read_text(encoding="utf-8")
    assert 'context = "jsonl://' in config
    assert (tmp_path / ".sprout" / "data" / "context").as_posix() in config
    assert "/Users/jason" not in config
    assert "SEAM_Sprout/Users" not in config
    assert "sprout_core.db" in config


# -- merging ----------------------------------------------------------------------


def test_partial_merge_keeps_other_fields() -> None:
    settings = settings_from_dict({"model": {"provider": "deepseek"}})
    assert settings.model.provider == "deepseek"
    assert settings.model.model == ""  # untouched sibling
    assert settings.storage.operational == _home_dsn("sprout_audit.db")


def test_nested_merge_only_overrides_given_keys() -> None:
    settings = settings_from_dict({"storage": {"operational": "memory"}})
    assert settings.storage.operational == "memory"
    assert settings.storage.knowledge == _home_dsn("sprout_knowledge.db")


def test_session_dsn_switches_backend() -> None:
    settings = settings_from_dict({"storage": {"session": "jsonl:///data/session.jsonl"}})
    assert settings.storage.session == "jsonl:///data/session.jsonl"
    assert settings.storage.operational == _home_dsn("sprout_audit.db")  # untouched


def test_storage_public_layer_names_are_accepted() -> None:
    settings = settings_from_dict(
        {
            "storage": {
                "core": "sqlite:///data/sprout_core.db",
                "conversation": "sqlite:///data/sprout_conversation.db",
                "audit": "sqlite:///data/sprout_audit.db",
            }
        }
    )
    assert settings.storage.core == "sqlite:///data/sprout_core.db"
    assert settings.storage.conversation == "sqlite:///data/sprout_conversation.db"
    assert settings.storage.audit == "sqlite:///data/sprout_audit.db"
    assert settings.storage.metadata == settings.storage.core
    assert settings.storage.session == settings.storage.conversation
    assert settings.storage.operational == settings.storage.audit


def test_unknown_top_level_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown_key"):
        settings_from_dict({"unknown_key": 1})


def test_unknown_nested_key_raises() -> None:
    with pytest.raises(ValueError, match="nope"):
        settings_from_dict({"model": {"nope": True}})


def test_scalar_for_table_setting_raises() -> None:
    with pytest.raises(ValueError, match="must be a table"):
        settings_from_dict({"model": "deepseek"})


def test_clients_list_becomes_tuple_of_settings() -> None:
    settings = settings_from_dict(
        {
            "mcp": {
                "clients": [
                    {"name": "fs", "command": "npx", "args": ["-y", "server-fs"]},
                ]
            }
        }
    )
    (client,) = settings.mcp.clients
    assert isinstance(client, MCPClientSettings)
    assert client.args == ("-y", "server-fs")  # list coerced to tuple


# -- TOML loading -----------------------------------------------------------------


def _write_config(path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_settings_from_explicit_file(tmp_path) -> None:
    config = _write_config(
        tmp_path / "sprout.toml",
        "\n".join(
            [
                "[model]",
                'provider = "deepseek"',
                'api_key_env = "DEEPSEEK_API_KEY"',
                "",
                "[[mcp.clients]]",
                'name = "fs"',
                'command = "npx"',
                'args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]',
                "",
                "[evolution]",
                "approval_required = false",
            ]
        ),
    )
    settings = load_settings(config)
    assert settings.model.provider == "deepseek"
    assert settings.mcp.clients[0].command == "npx"
    assert settings.mcp.clients[0].args[-1] == "/tmp"
    assert settings.evolution.approval_required is False


def test_load_settings_explicit_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.toml")


def test_load_settings_env_var_path(tmp_path, monkeypatch) -> None:
    config = _write_config(tmp_path / "env.toml", '[model]\nprovider = "deepseek"\n')
    monkeypatch.setenv("SPROUT_CONFIG", config)
    assert load_settings().model.provider == "deepseek"


def test_load_settings_env_var_missing_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPROUT_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(FileNotFoundError):
        load_settings()


def test_load_settings_falls_back_to_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPROUT_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_SEARCH_PATHS", (tmp_path / "nowhere.toml",))
    settings = load_settings()
    assert settings == default_settings()


def test_load_settings_discovers_config_in_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPROUT_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_SEARCH_PATHS", (tmp_path / "sprout.toml",))
    _write_config(tmp_path / "sprout.toml", '[model]\nprovider = "deepseek"\n')
    assert load_settings().model.provider == "deepseek"


# -- dump -------------------------------------------------------------------------


def test_dump_settings_is_plain_data() -> None:
    settings = settings_from_dict(
        {
            "mcp": {"clients": [{"name": "fs", "command": "npx"}]},
            "storage": {"operational": "memory"},
        }
    )
    data = dump_settings(settings)
    assert data["model"]["provider"] == "aiyallm"
    assert data["storage"]["operational"] == "memory"
    assert data["mcp"]["clients"][0]["name"] == "fs"
    import json

    json.dumps(data)  # must be JSON-able for `sprout info`


def test_provider_only_model_config_derives_default_route() -> None:
    settings = settings_from_dict(
        {
            "model": {
                "providers": [
                    {
                        "name": "deepseek",
                        "type": "openai_compatible",
                        "models": ["deepseek-v4-pro"],
                    }
                ]
            }
        }
    )
    assert settings.model.provider == "aiyallm"
    assert settings.model.model == "deepseek/deepseek-v4-pro"


def test_top_level_models_config_derives_default_route() -> None:
    settings = settings_from_dict(
        {
            "models": [
                {
                    "name": "deepseek",
                    "type": "openai_compatible",
                    "models": ["deepseek-v4-pro"],
                }
            ]
        }
    )
    assert settings.model.provider == "aiyallm"
    assert settings.model.model == "deepseek/deepseek-v4-pro"
    assert settings.model.providers[0]["name"] == "deepseek"


def test_provider_api_key_is_optional_and_empty_key_is_omitted() -> None:
    settings = settings_from_dict(
        {
            "models": [
                {
                    "name": "qwen",
                    "type": "openai_compatible",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "models": ["qwen3.8-flash"],
                    "api_key": "",
                },
                {
                    "name": "deepseek",
                    "type": "openai_compatible",
                    "models": ["deepseek-flash"],
                    "api_key": "user-supplied-key",
                },
            ]
        }
    )
    assert "api_key" not in settings.model.providers[0]
    assert settings.model.providers[1]["api_key"] == "user-supplied-key"

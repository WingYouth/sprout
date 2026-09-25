"""Scan-to-create Feishu setup: credential persistence and domain routing."""

from __future__ import annotations

import asyncio

from Sprout.cli.commands import gateway as gateway_cli
from Sprout.config.settings import Settings


async def _never_cancel() -> bool:
    await asyncio.Event().wait()
    return False


async def _cancel_now() -> bool:
    return True


async def test_setup_feishu_qr_saves_credentials(tmp_path, monkeypatch) -> None:
    settings = Settings()
    config = tmp_path / "sprout.toml"
    monkeypatch.setattr(gateway_cli, "_prompt_enter_to_cancel", _never_cancel)

    async def fake_register(on_qr_code, on_status_change=None, source=None, app_preset=None):
        on_qr_code({"url": "https://accounts.feishu.cn/launcher", "expire_in": 600})
        return {
            "client_id": "cli_test",
            "client_secret": "secret_test",
            "user_info": {"tenant_brand": "feishu"},
        }

    monkeypatch.setattr("lark_oapi.scene.registration.aregister_app", fake_register)

    ok = await gateway_cli._setup_feishu_qr(settings, config=str(config))

    assert ok is True
    assert settings.feishu.enabled is True
    assert settings.feishu.app_id == "cli_test"
    assert settings.feishu.app_secret == "secret_test"
    text = config.read_text(encoding="utf-8")
    assert 'app_id = "cli_test"' in text
    assert 'app_secret = "secret_test"' in text


async def test_setup_feishu_qr_switches_lark_domain(tmp_path, monkeypatch) -> None:
    settings = Settings()
    config = tmp_path / "sprout.toml"
    monkeypatch.setattr(gateway_cli, "_prompt_enter_to_cancel", _never_cancel)

    async def fake_register(on_qr_code, on_status_change=None, source=None, app_preset=None):
        on_qr_code({"url": "https://accounts.feishu.cn/launcher", "expire_in": 600})
        return {
            "client_id": "cli_test",
            "client_secret": "secret_test",
            "user_info": {"tenant_brand": "lark"},
        }

    monkeypatch.setattr("lark_oapi.scene.registration.aregister_app", fake_register)

    ok = await gateway_cli._setup_feishu_qr(settings, config=str(config))

    assert ok is True
    assert settings.feishu.domain == "lark"
    assert 'domain = "lark"' in config.read_text(encoding="utf-8")


async def test_setup_feishu_qr_cancelled(tmp_path, monkeypatch) -> None:
    settings = Settings()
    config = tmp_path / "sprout.toml"
    monkeypatch.setattr(gateway_cli, "_prompt_enter_to_cancel", _cancel_now)

    async def slow_register(on_qr_code, on_status_change=None, source=None, app_preset=None):
        await asyncio.sleep(10)
        return {"client_id": "cli_x", "client_secret": "secret_x"}

    monkeypatch.setattr("lark_oapi.scene.registration.aregister_app", slow_register)

    ok = await gateway_cli._setup_feishu_qr(settings, config=str(config))

    assert ok is False
    assert settings.feishu.app_id == ""
    assert not config.exists()


def test_ensure_default_workspace_registers_when_empty(tmp_path, monkeypatch) -> None:
    settings = Settings()
    config = tmp_path / "sprout.toml"

    async def fake_open(_settings):
        return "ws-123"

    monkeypatch.setattr(gateway_cli, "_open_cwd_workspace", fake_open)

    gateway_cli._ensure_default_workspace(settings, "feishu", config=str(config))

    assert settings.feishu.default_workspace_id == "ws-123"
    assert 'default_workspace_id = "ws-123"' in config.read_text(encoding="utf-8")


def test_ensure_default_workspace_skips_when_set(tmp_path, monkeypatch) -> None:
    settings = Settings()
    settings.feishu.default_workspace_id = "existing"
    config = tmp_path / "sprout.toml"
    opened: list[str] = []

    async def fake_open(_settings):
        opened.append("called")
        return "ws-new"

    monkeypatch.setattr(gateway_cli, "_open_cwd_workspace", fake_open)

    gateway_cli._ensure_default_workspace(settings, "feishu", config=str(config))

    assert opened == []
    assert settings.feishu.default_workspace_id == "existing"
    assert not config.exists()


def test_persist_default_workspace_updates_existing_section(tmp_path) -> None:
    config = tmp_path / "sprout.toml"
    config.write_text(
        '[feishu]\napp_id = "x"\ndefault_workspace_id = "old"\n',
        encoding="utf-8",
    )

    gateway_cli._persist_default_workspace("feishu", "new", str(config))

    text = config.read_text(encoding="utf-8")
    assert 'default_workspace_id = "new"' in text
    assert 'default_workspace_id = "old"' not in text
    assert 'app_id = "x"' in text

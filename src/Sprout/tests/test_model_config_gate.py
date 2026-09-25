from types import SimpleNamespace

from Sprout.cli.commands.model import model_configuration_issues
from Sprout.config.settings import ModelSettings
from Sprout.runtime.factory import _build_provider


def test_interactive_model_requires_real_provider(monkeypatch) -> None:
    settings = SimpleNamespace(
        model=SimpleNamespace(
            provider="aiyallm",
            model="echo",
            base_url="",
            api_key_env="",
        )
    )

    issues = model_configuration_issues(settings)

    assert issues
    assert any("echo" in issue for issue in issues)


def test_interactive_model_accepts_configured_provider(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL_KEY", "configured")
    settings = SimpleNamespace(
        model=SimpleNamespace(
            provider="openai_compatible",
            model="my-model",
            base_url="https://provider.example/v1",
            api_key_env="TEST_MODEL_KEY",
        )
    )

    assert model_configuration_issues(settings) == []


def test_aiyallm_does_not_require_api_key_env() -> None:
    settings = SimpleNamespace(
        model=SimpleNamespace(
            provider="aiyallm",
            model="configured-model",
            base_url="",
            api_key_env="",
        )
    )

    assert model_configuration_issues(settings) == []


def test_aiyallm_resolves_key_from_model_family(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-test-key")
    provider = _build_provider(
        "aiyallm",
        "deepseek-v4-pro",
        "https://provider.example/v1",
        "",
        ModelSettings(provider="aiyallm", model="deepseek-v4-pro"),
    )

    assert provider.name == "aiyallm"
    assert provider.model == "deepseek-v4-pro"

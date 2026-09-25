import sys
import types

import pytest

import Sprout.cli.i18n as i18n
from Sprout.cli.i18n import language_command, language_request
from Sprout.llm.language import detect_language


@pytest.fixture(autouse=True)
def force_hash_intent_embedding(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPROUT_CLI_INTENT_EMBEDDING_BACKEND", "hash")
    i18n._LANGUAGE_INTENT_EMBEDDER = None
    i18n._SEMANTIC_LANGUAGE_VECTORS = None
    yield
    i18n._LANGUAGE_INTENT_EMBEDDER = None
    i18n._SEMANTIC_LANGUAGE_VECTORS = None


def test_detects_non_latin_scripts() -> None:
    assert detect_language("请分析这个项目") == "zh"
    assert detect_language("このプロジェクトを分析してください") == "ja"
    assert detect_language("이 프로젝트를 분석해 주세요") == "ko"
    assert detect_language("Проанализируй этот проект") == "ru"


def test_detects_latin_language_markers_and_defaults_to_english() -> None:
    assert detect_language("¿Cómo puedes ayudarme?") == "es"
    assert detect_language("Como você pode me ajudar?") == "pt"
    assert detect_language("Analyze this project") == "en"


def test_extracts_explicit_language_switch_requests() -> None:
    assert language_request("请切换到英文") == "en"
    assert language_request("切换界面语言为英文") == "en"
    assert language_request("换回中文") == "zh"
    assert language_request("换为日语") == "ja"
    assert language_request("switch language to Japanese") == "ja"
    assert language_command("切换界面语言为中文") == ("/language", "zh")
    assert language_request("请分析这个项目") is None


def test_switches_between_all_supported_languages_from_natural_phrases() -> None:
    examples = {
        "use English": "en",
        "日本語に切り替えて": "ja",
        "한국어로 바꿔줘": "ko",
        "переключи на русский": "ru",
        "cambiar a español": "es",
        "mudar para português": "pt",
        "換回繁體中文": "zh-Hant",
        "切换成简体中文": "zh",
    }
    for text, expected in examples.items():
        assert language_request(text) == expected


def test_embedding_fallback_handles_semantic_language_requests() -> None:
    examples = {
        "please respond in Portuguese from now on": "pt",
        "能不能讲日本那边的话": "ja",
        "用我刚才那种中文回答": "zh",
        "respond in English from now on": "en",
        "responde en español": "es",
    }
    for text, expected in examples.items():
        assert language_request(text) == expected


def test_embedding_fallback_avoids_language_mentions_without_switch_intent() -> None:
    assert language_request("我在学日语") is None


def test_cli_intent_embedder_prefers_sentence_transformer_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_models = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            loaded_models.append(model_name)

        def encode(self, text: str, **_: object) -> list[float]:
            return [3.0, 4.0] if text else [0.0, 0.0]

    monkeypatch.setenv("SPROUT_CLI_INTENT_EMBEDDING_BACKEND", "auto")
    monkeypatch.setenv("SPROUT_CLI_INTENT_EMBEDDING_MODEL", "fake/tiny-multilingual")
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedder = i18n._CliIntentEmbedder(dim=8)

    assert loaded_models == ["fake/tiny-multilingual"]
    assert embedder("hello") == [0.6, 0.8]

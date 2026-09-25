"""Lightweight language detection for response-language hints."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")

_SPANISH_MARKERS = {"el", "la", "los", "las", "que", "cómo", "para", "una"}
_PORTUGUESE_MARKERS = {"o", "a", "os", "as", "que", "como", "para", "uma"}


def detect_language(text: str) -> str:
    """Return a best-effort language code for the user's latest message."""
    if not text.strip():
        return "en"
    if _HANGUL_RE.search(text):
        return "ko"
    if _HIRAGANA_KATAKANA_RE.search(text):
        return "ja"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _CJK_RE.search(text):
        return "zh"

    words = set(re.findall(r"[a-zA-ZÀ-ÿ]+", text.casefold()))
    if words & _SPANISH_MARKERS:
        return "es"
    if words & _PORTUGUESE_MARKERS:
        return "pt"
    return "en"

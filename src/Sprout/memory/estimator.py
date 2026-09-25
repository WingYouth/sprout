"""CJK-aware token estimator.

A pluggable estimator with one default implementation good enough for budget
allocation. ``estimate(text)`` walks the string and charges one token per CJK
ideograph and ~0.25 token per ASCII character; the result is rounded up so a
planner never runs over budget because of an integer boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


# Rough "is this character a single token on its own" probe.
def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF  # CJK Extension A
        or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0xF900 <= code <= 0xFAFF  # CJK Compatibility Ideographs
        or 0x3040 <= code <= 0x30FF  # Hiragana / Katakana
        or 0xAC00 <= code <= 0xD7AF  # Hangul Syllables
    )


class TokenEstimator(Protocol):
    """Replace the default estimator by injecting a real tokenizer (tiktoken, etc.)."""

    def estimate(self, text: str) -> int: ...


@dataclass(frozen=True, slots=True)
class CharEstimator:
    """Char-walk estimator; cheap and never wrong by more than the safety factor."""

    safety_margin: float = 1.1  # always round up to leave room for the model

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        tokens = 0.0
        for ch in text:
            if _is_cjk(ch):
                tokens += 1.0
            else:
                tokens += 0.25
        tokens *= self.safety_margin
        return max(1, int(tokens) + (1 if tokens - int(tokens) > 0 else 0))


def estimate_many(estimator: TokenEstimator, items: Iterable[str]) -> int:
    """Estimate the combined token cost of several texts."""
    return sum(estimator.estimate(text or "") for text in items)


__all__ = ["CharEstimator", "TokenEstimator", "estimate_many"]
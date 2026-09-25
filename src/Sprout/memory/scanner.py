"""Memory scanner: reject values that would be a prompt-injection payload or
that smuggle credentials into the agent's system prompt.

The scanner is deliberately strict — a *false positive* costs nothing (the
agent can re-enter the fact via a richer prompt); a *false negative* hands
the model a hostile instruction.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# "Ignore everything above and …" style injections.
_INJECTION_PATTERNS = (
    # "ignore all previous instructions" or "ignore prior rules" — let any
    # qualifier word sit between the modifier and the target noun.
    re.compile(
        r"ignore\s+(?:all\s+|previous\s+|above\s+|prior\s+)?"
        r"(?:\w+\s+){0,3}?(instructions?|rules?|prompts?|directives?)",
        re.I,
    ),
    re.compile(r"you\s+are\s+now\s+(?:a\s+)?", re.I),
    re.compile(r"system\s*:\s*", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"<\|im_end\|>", re.I),
    re.compile(r"act\s+as\s+(?:an?\s+|the\s+)?developer\s+mode", re.I),
    re.compile(r"disregard\s+(?:the\s+)?(?:above|prior|previous|all)", re.I),
    re.compile(r"override\s+(?:the\s+)?(?:system|safety|rules?)", re.I),
)

# Obvious credential smuggling: AWS keys, private keys, GitHub PATs, JWTs.
_CREDENTIAL_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),  # GitHub PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
)


@dataclass(frozen=True, slots=True)
class ScanResult:
    accepted: bool
    reasons: tuple[str, ...] = ()


class MemoryScanner:
    """Reject inputs that look like injections, credentials, or invisible Unicode."""

    def scan(self, value: str) -> ScanResult:
        reasons: list[str] = []
        if not value or not value.strip():
            return ScanResult(False, ("empty value",))
        for char in value:
            if unicodedata.category(char).startswith("C"):
                reasons.append(f"control/format character U+{ord(char):04X}")
                break
            if unicodedata.category(char) == "Cf" and char not in ("\n", "\r", "\t"):
                reasons.append(f"invisible Unicode U+{ord(char):04X}")
                break
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(value):
                reasons.append(f"injection pattern {pattern.pattern!r}")
                break
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(value):
                reasons.append(f"credential pattern {pattern.pattern!r}")
                break
        return ScanResult(accepted=not reasons, reasons=tuple(reasons))


__all__ = ["MemoryScanner", "ScanResult"]
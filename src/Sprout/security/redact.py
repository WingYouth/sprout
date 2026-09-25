"""The single redaction entry point for the whole runtime (AUTHZ §4.2).

Three layers, applied in order:

1. **Known values** — every secret the caller declares (injected env names, an
   explicit value list) is replaced verbatim.
2. **Patterns** — credentials that show up without being declared: ``sk-…``,
   ``ghp_…``, ``Bearer …``, ``api_key=…``, PEM blocks, JWTs, ``user:pass@``
   URLs. This mirrors Hermes' MCP error-scrubbing list.
3. **Invisible Unicode** — zero-width and bidi-control characters are a
   smuggling vector, so callers can *reject* text containing them instead of
   silently persisting it.

Consumers: ``ProcessBroker`` output, MCP error messages, trajectory event
payloads, the audit stream, and ``ReadBroker``'s ``ALLOW_REDACTED`` reads.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.security.secrets import SecretProvider

REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class RedactionPattern:
    """A named credential pattern; ``group`` selects the part to mask."""

    id: str
    pattern: re.Pattern[str]
    group: int = 0


DEFAULT_PATTERNS: tuple[RedactionPattern, ...] = (
    RedactionPattern("provider-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    RedactionPattern("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    RedactionPattern("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    RedactionPattern("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    RedactionPattern("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}")),
    RedactionPattern(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ),
    RedactionPattern(
        "pem-block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    RedactionPattern(
        "key-value",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?key|auth[_-]?token|client[_-]?secret|"
            r"password|passwd|secret|token)\b\s*[:=]\s*[\"']?([A-Za-z0-9._\-/+]{8,})"
        ),
        group=1,
    ),
    RedactionPattern(
        "url-credentials",
        re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@"),
    ),
)

# Zero-width joiners, bidi overrides, and other invisible formatters.
INVISIBLE_CHARACTERS = (
    "\u00ad\u200b\u200c\u200d\u2060\ufeff"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


class InvisibleCharacterError(ValueError):
    """Raised when text destined for storage carries invisible Unicode."""


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    count: int

    def __bool__(self) -> bool:
        return self.count > 0


class Redactor:
    """Value + pattern + invisible-character scrubbing in one object."""

    def __init__(
        self,
        *,
        provider: SecretProvider | None = None,
        secret_names: Sequence[str] = (),
        known_values: Sequence[str] = (),
        patterns: Sequence[RedactionPattern] = DEFAULT_PATTERNS,
    ) -> None:
        self._provider = provider
        self._secret_names = tuple(secret_names)
        self._known_values = tuple(value for value in known_values if value)
        self._patterns = tuple(patterns)

    def redact(self, text: str) -> RedactionResult:
        """Mask known values, then patterns; return the text and match count."""
        if not text:
            return RedactionResult(text, 0)
        redacted = text
        count = 0
        for value in self._values():
            if value in redacted:
                count += redacted.count(value)
                redacted = redacted.replace(value, REDACTED)
        for pattern in self._patterns:
            redacted, hits = _substitute(redacted, pattern)
            count += hits
        return RedactionResult(redacted, count)

    def scrub(self, text: str) -> str:
        """Convenience wrapper for callers that only need the text."""
        return self.redact(text).text

    def redact_mapping(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Redact every string value in a one-level mapping (event payloads)."""
        cleaned: dict[str, object] = {}
        for key, value in payload.items():
            cleaned[key] = self.scrub(value) if isinstance(value, str) else value
        return cleaned

    def _values(self) -> tuple[str, ...]:
        values = list(self._known_values)
        if self._provider is not None:
            for name in self._secret_names:
                resolved = self._provider.get(name)
                if resolved:
                    values.append(resolved)
        return tuple(values)

    # -- invisible characters -------------------------------------------------
    @staticmethod
    def has_invisible(text: str) -> bool:
        return any(char in text for char in INVISIBLE_CHARACTERS)

    @staticmethod
    def strip_invisible(text: str) -> str:
        return "".join(char for char in text if char not in INVISIBLE_CHARACTERS)

    @staticmethod
    def check_clean(text: str) -> str | None:
        """Return a rejection reason when the text carries invisible characters."""
        if Redactor.has_invisible(text):
            return "Text contains invisible Unicode characters"
        return None

    @staticmethod
    def require_clean(text: str) -> str:
        """Fail closed for storage paths that must not persist smuggled text."""
        reason = Redactor.check_clean(text)
        if reason is not None:
            raise InvisibleCharacterError(reason)
        return text


def _substitute(text: str, pattern: RedactionPattern) -> tuple[str, int]:
    if pattern.group == 0:
        return pattern.pattern.subn(REDACTED, text)
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        start, end = match.span(pattern.group)
        prefix = match.group(0)[: start - match.start()]
        suffix = match.group(0)[end - match.start() :]
        return f"{prefix}{REDACTED}{suffix}"

    return pattern.pattern.sub(_replace, text), count

"""Secret resolution. Keys are read from environment variables only.

``SecretProvider`` is the seam that lets keychain or vault backends land later
without touching every ``get_secret`` call site (AUTHZ §4.1). Configuration
stores environment variable *names*, never values — ``Sprout.config`` has no
field that can hold a secret, and a test asserts serialized settings never leak
one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "zhipu": "ZHIPUAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

#: Name markers used by :meth:`EnvSecretProvider.list_names`.
SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


@runtime_checkable
class SecretProvider(Protocol):
    """Source of secret values, addressed by name."""

    def get(self, name: str) -> str | None: ...

    def list_names(self) -> Sequence[str]: ...


def get_secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


class EnvSecretProvider:
    """The default provider: secrets live in the process environment."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def get(self, name: str) -> str | None:
        value = (self._environ.get(name) or "").strip()
        return value or None

    def list_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in sorted(self._environ)
            if any(marker in name.upper() for marker in SECRET_NAME_MARKERS)
        )


def default_secret_provider() -> SecretProvider:
    return EnvSecretProvider()


def resolve_api_key(provider: str, *, env_name: str | None = None) -> str | None:
    """Resolve the API key for a provider, trying the explicit env name first."""
    candidates: list[str] = []
    if env_name:
        candidates.append(env_name)
    candidates.append(f"{provider.strip().upper().replace('-', '_')}_API_KEY")
    if provider in PROVIDER_API_KEY_ENV:
        candidates.append(PROVIDER_API_KEY_ENV[provider])
    seen: set[str] = set()
    for name in candidates:
        if name and name not in seen:
            seen.add(name)
            key = get_secret(name)
            if key:
                return key
    return None

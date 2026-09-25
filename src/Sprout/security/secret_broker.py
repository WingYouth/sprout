"""Secret injection, child-process environment policy, and redaction (AUTHZ §4).

Three jobs, one object:

* :meth:`SecretBroker.inject_env` — resolve named secrets into a mapping;
* :meth:`SecretBroker.child_env` — build a child process environment from a
  **whitelist** only. Before this, subprocesses inherited the whole parent
  environment, so an unrelated API key was one ``env`` call away from a model;
* :meth:`SecretBroker.redact` — delegate to the runtime-wide
  :class:`~Sprout.security.redact.Redactor` so process output, MCP errors, and
  audit payloads all share one pattern list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatch

from Sprout.security.redact import RedactionResult, Redactor
from Sprout.security.secrets import EnvSecretProvider, SecretProvider, default_secret_provider

#: Variables a child process needs to function; everything else is stripped.
DEFAULT_ENV_WHITELIST: tuple[str, ...] = (
    "PATH",
    "PATHEXT",
    "HOME",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "SHELL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "COMSPEC",
    "SYSTEMROOT",
    "WINDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "VIRTUAL_ENV",
    "XDG_*",
)


class SecretBroker:
    """Resolves secret references without exposing values to normal contexts."""

    def __init__(
        self,
        provider: SecretProvider | None = None,
        *,
        redactor: Redactor | None = None,
        env_whitelist: Sequence[str] = DEFAULT_ENV_WHITELIST,
    ) -> None:
        self._provider: SecretProvider = provider or EnvSecretProvider()
        self._redactor = redactor
        self._whitelist = tuple(env_whitelist)

    @property
    def provider(self) -> SecretProvider:
        return self._provider

    def inject_env(
        self,
        secret_names: Sequence[str],
        *,
        base_env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env or {})
        for name in secret_names:
            value = self._provider.get(name)
            if value is not None:
                env[name] = value
        return env

    def redact(self, text: str, secret_names: Sequence[str] = ()) -> str:
        """Mask known secret values and credential patterns; returns the text."""
        return self._redactor_for(secret_names).scrub(text)

    def redact_result(self, text: str, secret_names: Sequence[str] = ()) -> RedactionResult:
        """Same as :meth:`redact`, plus the number of masked matches."""
        return self._redactor_for(secret_names).redact(text)

    def child_env(
        self,
        *,
        base_env: Mapping[str, str] | None = None,
        required: Sequence[str] = (),
        extra: Mapping[str, str] | None = None,
        secret_names: Sequence[str] = (),
    ) -> dict[str, str]:
        """Whitelisted child environment, plus declared requirements and secrets."""
        source = dict(base_env if base_env is not None else {})
        allowed: set[str] = set()
        for key in source:
            if any(fnmatch(key, pattern) for pattern in self._whitelist):
                allowed.add(key)
        for name in required:
            if name in source:
                allowed.add(name)
        env = {key: source[key] for key in allowed}
        if extra:
            env.update(extra)
        env.update(self.inject_env(secret_names, base_env=env))
        return env

    def _redactor_for(self, secret_names: Sequence[str]) -> Redactor:
        if not secret_names:
            return self._redactor or Redactor(provider=self._provider)
        return self._redactor or Redactor(provider=self._provider, secret_names=secret_names)


def default_provider() -> SecretProvider:
    """Backwards-compatible alias for the environment provider factory."""
    return default_secret_provider()

"""Settings loading: defaults, ``sprout.toml`` discovery, and deep merging."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

from Sprout.config.defaults import default_settings
from Sprout.config.settings import (
    ClassifySettings,
    MCPClientSettings,
    MCPPrincipalSettings,
    Settings,
)

T = TypeVar("T")

_SEARCH_PATHS = (Path.home() / ".sprout" / "sprout.toml",)


def load_env_file(path: str | Path = Path(".env")) -> None:
    """Load ``KEY=VALUE`` entries from a local .env into ``os.environ``.

    Existing environment variables win; the file only fills in missing values.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def update_env_file(
    path: str | Path,
    values: Mapping[str, str],
) -> None:
    """Upsert ``KEY=VALUE`` entries into a local .env, preserving other lines."""
    env_path = Path(path)
    lines: list[str] = []
    seen: set[str] = set()
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                lines.append(line)
                continue
            key = stripped.partition("=")[0].strip()
            if key and key not in values:
                lines.append(line)
                seen.add(key)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from ``path``, else ``SPROUT_CONFIG``, else the search paths.

    Falls back to offline defaults when no configuration file exists.
    """
    candidates: list[Path]
    if path is not None:
        candidates = [Path(path)]
    elif (env_path := os.environ.get("SPROUT_CONFIG")) :
        candidates = [Path(env_path)]
    else:
        candidates = list(_SEARCH_PATHS)

    for candidate in candidates:
        if candidate.is_file():
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            return settings_from_dict(data)

    if path is not None or os.environ.get("SPROUT_CONFIG"):
        # An explicit location was requested but not found; fail loudly.
        requested = path or os.environ["SPROUT_CONFIG"]
        raise FileNotFoundError(f"Configuration file not found: {requested}")
    return default_settings()


def settings_from_dict(data: Mapping[str, Any], base: Settings | None = None) -> Settings:
    """Deep-merge a plain mapping onto the default settings; unknown keys raise."""
    data = _normalize_storage_aliases(data)
    data = _normalize_model_routes(_normalize_models_alias(data))
    return _apply(base or default_settings(), data)


def _normalize_models_alias(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept the public top-level ``[[models]]`` configuration surface."""
    models = data.get("models")
    if not isinstance(models, list):
        return data
    if "model" in data:
        raise ValueError("Use either [[models]] or [model], not both")
    normalized = dict(data)
    normalized.pop("models", None)
    normalized["model"] = {"providers": _normalize_provider_entries(models)}
    return normalized


def _normalize_provider_entries(entries: list[Any]) -> list[Any]:
    """Drop empty optional credentials before passing entries to aiyallm."""
    normalized: list[Any] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            normalized.append(entry)
            continue
        item = dict(entry)
        if not str(item.get("api_key", "")).strip():
            item.pop("api_key", None)
        normalized.append(item)
    return normalized


def _normalize_model_routes(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Allow advanced configs to declare only ``[[models]]``.

    The first provider/model becomes the default aiyallm route unless the
    caller explicitly supplied ``provider`` or ``model`` in ``[model]``.
    """
    model = data.get("model")
    if not isinstance(model, Mapping):
        return data
    providers = model.get("providers")
    if not isinstance(providers, list) or not providers:
        return data
    providers = _normalize_provider_entries(providers)
    first = providers[0]
    if not isinstance(first, Mapping):
        return data
    provider_name = str(first.get("name", "")).strip()
    models = first.get("models")
    first_model = ""
    if isinstance(models, list) and models:
        first_model = str(models[0]).strip()
    updates = {**model, "providers": providers}
    if not str(updates.get("provider", "")).strip() and provider_name:
        updates["provider"] = "aiyallm"
    if not str(updates.get("model", "")).strip() and provider_name and first_model:
        updates["model"] = f"{provider_name}/{first_model}"
    return {**data, "model": updates}


def _normalize_storage_aliases(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept the public ``sprout_*`` storage names as well as legacy fields.

    ``guidance.md`` section 19 names the authorities ``core``, ``conversation``,
    ``audit``, and ``usage``. The internal :class:`StorageSettings` fields still
    use the historical implementation names, so config files written against
    the new public surface are translated here instead of forcing every caller
    to know both vocabularies.
    """
    storage = data.get("storage")
    if not isinstance(storage, Mapping):
        return data
    storage = dict(storage)
    aliases = {
        "core": "metadata",
        "conversation": "session",
        "audit": "operational",
    }
    for public, internal in aliases.items():
        if public in storage:
            storage.setdefault(internal, storage[public])
            storage.pop(public, None)
    return {**data, "storage": storage}


def _apply[T](target: T, data: Mapping[str, Any]) -> T:
    if not is_dataclass(target) or isinstance(target, type):
        raise TypeError(f"Cannot merge settings into {type(target).__name__}")
    known = {field.name for field in fields(target)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"Unknown setting(s) {sorted(unknown)} for {type(target).__name__}"
        )
    updates: dict[str, Any] = {}
    for key, value in data.items():
        current = getattr(target, key)
        if key == "classify" and isinstance(current, ClassifySettings):
            # ``[security.classify]`` accepts glob keys directly *and* nested under
            # ``rules``; kind names are validated by the classifier, not at load time.
            updates[key] = _parse_classify(value)
        elif is_dataclass(current) and not isinstance(current, type):
            if not isinstance(value, Mapping):
                raise ValueError(f"Setting '{key}' must be a table")
            updates[key] = _apply(current, value)
        elif key == "clients":
            parsed: list[MCPClientSettings] = []
            for item in value:
                if isinstance(item, MCPClientSettings):
                    parsed.append(item)
                    continue
                client = dict(item)
                client["args"] = tuple(client.get("args", ()))
                principal = client.get("principal")
                if isinstance(principal, Mapping):
                    principal = dict(principal)
                    principal["roles"] = tuple(principal.get("roles", ()))
                    client["principal"] = MCPPrincipalSettings(**principal)
                parsed.append(MCPClientSettings(**client))
            updates[key] = tuple(parsed)
        elif isinstance(current, tuple) and isinstance(value, list):
            updates[key] = tuple(value)
        else:
            updates[key] = value
    return replace(target, **updates)


def _parse_classify(value: Any) -> ClassifySettings:
    """Accept both ``[security.classify]`` glob keys and ``[security.classify.rules]``."""
    if not isinstance(value, Mapping):
        raise ValueError("Setting 'classify' must be a table")
    data = dict(value)
    rules = dict(data.pop("rules", {}) or {})
    rules.update({str(key): str(item) for key, item in data.items()})
    return ClassifySettings(rules=rules)


def dump_settings(settings: Settings) -> dict[str, Any]:
    """Convert settings back into a plain (JSON-able) mapping, for ``sprout info``."""

    def _dump(obj: Any) -> Any:
        if is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: _dump(getattr(obj, f.name)) for f in fields(obj)}
        if isinstance(obj, tuple):
            return [_dump(item) for item in obj]
        if isinstance(obj, dict):
            return {key: _dump(value) for key, value in obj.items()}
        return obj

    data = _dump(settings)
    storage = data.get("storage")
    if isinstance(storage, dict):
        aliases = {
            "core": storage.get("metadata"),
            "conversation": storage.get("session"),
            "audit": storage.get("operational"),
        }
        for public, value in aliases.items():
            if value is not None:
                storage.setdefault(public, value)
    return data


MASKED = "[REDACTED]"


def mask_settings(settings: Settings) -> dict[str, Any]:
    """``dump_settings`` with anything credential-shaped masked (AUTHZ §4.1).

    ``/api/settings`` is a read-only view for the console, but ``dump_settings``
    emitted DSN passwords (``neo4j://user:pass@host``), the outbound
    allow/deny lists, the SSRF exemptions and the audit path — a complete map of
    the deployment's boundary. The shape is preserved so the console still works.
    """
    from Sprout.security.redact import Redactor

    return _mask(dump_settings(settings), Redactor())


def _mask(node: Any, redactor: Any, *, key: str = "") -> Any:
    if isinstance(node, dict):
        if key == "env":
            # ``[[mcp.clients]].env`` holds literal values, not names.
            return {item: MASKED for item in node}
        return {item: _mask(value, redactor, key=item) for item, value in node.items()}
    if isinstance(node, list):
        return [_mask(item, redactor) for item in node]
    if isinstance(node, str):
        return redactor.scrub(node)
    return node

"""JSON-safe codec for workspace analysis snapshots.

The analysis object is a frozen-dataclass graph with ``Path``, ``datetime``,
``enum``, and ``tuple`` leaves. This module converts it to plain JSON and back
so the Redis hot lane can hold a full snapshot that a later process can reuse
without re-scanning the workspace.
"""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints


def to_jsonable(value: Any) -> Any:
    """Recursively convert a workspace value into plain JSON primitives."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": _qualname(type(value)),
            "fields": {
                field.name: to_jsonable(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, Path):
        return {"__path__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, Enum):
        return {"__enum__": _qualname(type(value)), "value": value.value}
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def from_jsonable(value: Any, target_type: Any) -> Any:
    """Reconstruct a value from its JSON-safe form, guided by ``target_type``."""
    if get_origin(target_type) is Union:
        non_none = [arg for arg in get_args(target_type) if arg is not type(None)]
        if value is None:
            return None
        if non_none:
            return from_jsonable(value, non_none[0])

    origin = get_origin(target_type)
    if origin is tuple:
        item_type = get_args(target_type)[0] if get_args(target_type) else Any
        return tuple(from_jsonable(item, item_type) for item in (value or ()))

    if origin in (dict, Mapping) or target_type in (dict, Mapping):
        value_type = get_args(target_type)[1] if get_args(target_type) else Any
        return {
            str(key): from_jsonable(item, value_type)
            for key, item in (value or {}).items()
        }

    if isinstance(target_type, type):
        if issubclass(target_type, Path):
            return Path(value["__path__"] if isinstance(value, dict) else value)
        if issubclass(target_type, datetime):
            raw = value["__datetime__"] if isinstance(value, dict) else value
            return datetime.fromisoformat(raw)
        if issubclass(target_type, Enum):
            if isinstance(value, dict):
                cls = _import(value["__enum__"])
                return cls(value["value"])
            return target_type(value)

    if isinstance(value, dict) and "__dataclass__" in value:
        cls = _import(value["__dataclass__"])
        hints = get_type_hints(cls)
        kwargs = {
            name: from_jsonable(field_value, hints.get(name, Any))
            for name, field_value in value["fields"].items()
        }
        return cls(**kwargs)

    if isinstance(value, dict) and "__path__" in value:
        return Path(value["__path__"])
    if isinstance(value, dict) and "__datetime__" in value:
        return datetime.fromisoformat(value["__datetime__"])
    if isinstance(value, dict) and "__enum__" in value:
        return _import(value["__enum__"])(value["value"])

    return value


def _qualname(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _import(qualname: str) -> type:
    module_name, _, name = qualname.rpartition(".")
    return getattr(importlib.import_module(module_name), name)


__all__ = ["from_jsonable", "to_jsonable"]

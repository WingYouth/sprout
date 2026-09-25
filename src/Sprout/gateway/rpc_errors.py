"""Stable RPC error codes."""

from __future__ import annotations

from enum import StrEnum


class RPCErrorCode(StrEnum):
    PARSE_ERROR = "PARSE_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_PARAMS = "INVALID_PARAMS"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"

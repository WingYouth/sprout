"""Rootstock error types shared by every backend."""

from __future__ import annotations


class RootstockUnavailableError(RuntimeError):
    """A reserved backend slot is configured but not usable yet.

    Raised when the client library is missing or the adapter wiring for a
    reserved backend (Milvus, Neo4j, Redis) has not been implemented.
    """

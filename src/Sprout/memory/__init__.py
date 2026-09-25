"""Heartwood (心材) — the memory layer of SEAM_Sprout.

The Hermes model, adapted to Sprout:

- Curated, hard-capped facts live as ``MEMORY.md`` / ``USER.md`` files under a
  memory home directory. Writes go through a scanner; the cap is enforced in
  characters.
- Cross-session recall uses FTS5 over the session layer (``sprout_conversation.db``).
- Frozen snapshots at session start preserve the LLM prefix cache.

Public surface: :class:`~Sprout.memory.contract.MemoryStore` and
:class:`~Sprout.memory.contract.SessionSearch`, plus their backends and
the offline composer / scanner / snapshot / compactor machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from Sprout.memory.contract import MemoryStore, SessionSearch
from Sprout.memory.estimator import TokenEstimator

if TYPE_CHECKING:
    from Sprout.memory.backends.file_system import FileSystemMemoryStore
    from Sprout.memory.backends.memory_store import MemoryMemoryStore
    from Sprout.memory.backends.session_search import (
        MemorySessionSearch,
        SqliteSessionSearch,
    )
    from Sprout.memory.budget import Budget, BudgetAllocator, TokenEstimator
    from Sprout.memory.compactor import SessionCompactor
    from Sprout.memory.composer import ContextComposer
    from Sprout.memory.scanner import MemoryScanner

_LAZY: frozenset[str] = frozenset(
    {
        "MemoryMemoryStore",
        "FileSystemMemoryStore",
        "MemorySessionSearch",
        "SqliteSessionSearch",
        "Budget",
        "BudgetAllocator",
        "ContextComposer",
        "MemoryScanner",
        "SessionCompactor",
        "TokenEstimator",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        if name == "MemoryMemoryStore":
            from Sprout.memory.backends.memory_store import MemoryMemoryStore

            return MemoryMemoryStore
        if name == "FileSystemMemoryStore":
            from Sprout.memory.backends.file_system import FileSystemMemoryStore

            return FileSystemMemoryStore
        if name in {"MemorySessionSearch", "SqliteSessionSearch"}:
            from Sprout.memory.backends import session_search

            return getattr(session_search, name)
        if name in {"Budget", "BudgetAllocator", "TokenEstimator"}:
            from Sprout.memory import budget

            return getattr(budget, name)
        if name == "ContextComposer":
            from Sprout.memory.composer import ContextComposer

            return ContextComposer
        if name == "MemoryScanner":
            from Sprout.memory.scanner import MemoryScanner

            return MemoryScanner
        if name == "SessionCompactor":
            from Sprout.memory.compactor import SessionCompactor

            return SessionCompactor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MemoryStore",
    "SessionSearch",
    "MemoryMemoryStore",
    "FileSystemMemoryStore",
    "MemorySessionSearch",
    "SqliteSessionSearch",
    "Budget",
    "BudgetAllocator",
    "ContextComposer",
    "MemoryScanner",
    "SessionCompactor",
    "TokenEstimator",
]

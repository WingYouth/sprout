"""Heartwood backend factories.

- :class:`~Sprout.memory.backends.file_system.FileSystemMemoryStore`
  (the default; ``MEMORY.md``/``USER.md`` under a home directory)
- :class:`~Sprout.memory.backends.memory_store.MemoryMemoryStore`
  (in-memory; tests, ephemeral runtimes)
- :class:`~Sprout.memory.backends.session_search.SqliteSessionSearch`
  and :class:`~Sprout.memory.backends.session_search.MemorySessionSearch`
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Sprout.memory.contract import MemoryStore, SessionSearch

if TYPE_CHECKING:
    pass


def create_memory_store(
    spec: str | dict, home_dir: str | None = None
) -> MemoryStore:
    """Resolve a memory backend.

    ``spec`` is one of:

    - ``"memory"`` or ``"memory://"`` → :class:`MemoryMemoryStore`
    - ``"file"`` / ``"file://"`` → :class:`FileSystemMemoryStore`
      under ``home_dir`` (defaults to ``~/.sprout/data/memory``).
    - ``"file:///abs/path"`` → :class:`FileSystemMemoryStore` under that path.
    """
    from pathlib import Path

    if isinstance(spec, dict):
        kind = spec.get("kind", "file")
        home = (
            spec.get("home")
            or home_dir
            or (Path.home() / ".sprout" / "data" / "memory").as_posix()
        )
    else:
        if spec.startswith("file://"):
            kind = "file"
            home = spec[len("file://"):]
        elif spec.startswith("file:"):
            kind = "file"
            home = spec[len("file:"):] or home_dir
        elif spec in ("memory", "memory://"):
            kind = "memory"
            home = None
        elif spec == "file" or spec == "":
            kind = "file"
            home = home_dir or (Path.home() / ".sprout" / "data" / "memory").as_posix()
        else:
            kind = "file"
            home = spec
    if kind == "memory":
        from Sprout.memory.backends.memory_store import MemoryMemoryStore

        return MemoryMemoryStore()
    if kind == "file":
        from Sprout.memory.backends.file_system import FileSystemMemoryStore

        return FileSystemMemoryStore(Path(home))
    raise ValueError(f"Unknown memory backend kind: {kind!r}")


__all__ = ["MemoryStore", "SessionSearch", "create_memory_store"]

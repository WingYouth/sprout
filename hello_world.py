"""Root-level reference example: the smallest complete SEAM Sprout target.

This file is deliberately *outside* ``src/Sprout``. It is the "hello world"
the runtime can be pointed at end to end: a module with a pure function, a
``main()`` entry point, and a self-check that needs no test runner.

    python hello_world.py     # prints: Hello, World!

The contract is pinned by ``src/Sprout/tests/test_hello_world.py``.
"""

from __future__ import annotations

GREETING = "Hello, World!"

__all__ = ["GREETING", "hello", "main"]


def hello(name: str | None = None) -> str:
    """Return a greeting for ``name``, falling back to :data:`GREETING`.

    Printing is the caller's job: this stays a pure function so it can be
    asserted on directly.
    """
    if name is None or not name.strip():
        return GREETING
    return f"Hello, {name.strip()}!"


def main() -> None:
    """Print the default greeting."""
    print(hello())


def _self_check() -> None:
    """Assert the module's own contract; used by the test suite and ad hoc runs."""
    assert GREETING == "Hello, World!"
    assert hello() == GREETING
    assert hello(None) == GREETING
    assert hello("") == GREETING
    assert hello("   ") == GREETING
    assert hello("\t\n") == GREETING
    assert hello("Sprout") == "Hello, Sprout!"
    assert hello("  Sprout  ") == "Hello, Sprout!"


if __name__ == "__main__":
    main()

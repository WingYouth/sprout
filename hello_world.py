"""Minimal hello-world entry point for the SEAM Sprout repository.

Run it directly:

    python hello_world.py

It has no imports from ``Sprout`` on purpose: this is a smoke script that must
work before the runtime, storage, or configuration layers are set up.
"""

from __future__ import annotations

GREETING = "Hello, World!"


def main() -> str:
    """Print the greeting and return it, so callers can assert on the value."""
    print(GREETING)
    return GREETING


if __name__ == "__main__":
    main()

"""Minimal standalone smoke script: print a greeting."""

from __future__ import annotations


def greet(name: str = "World") -> str:
    """Return a greeting for ``name``."""
    return f"Hello, {name}!"


def main() -> int:
    """Print the default greeting and report success."""
    print(greet())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

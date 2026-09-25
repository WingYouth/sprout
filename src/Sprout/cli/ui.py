"""Shared presentation helpers for the ``sprout`` CLI.

The command output is intentionally consistent: purple is used for structure,
bright-white for important values, and green/yellow/red only for status.
"""

from __future__ import annotations

from typing import Any

import typer

PURPLE = (168, 85, 247)
LIGHT_PURPLE = (216, 180, 254)
MUTED = typer.colors.BRIGHT_BLACK


def text(value: Any, *, fg: Any = PURPLE, bold: bool = False) -> str:
    """Style a value with the default purple accent."""
    return typer.style(str(value), fg=fg, bold=bold)


def muted(value: Any) -> str:
    """Return a muted string for secondary detail."""
    return typer.style(str(value), fg=MUTED)


def label(value: Any) -> str:
    """Return a purple, bold label for a key-value line."""
    return typer.style(str(value), fg=PURPLE, bold=True)


def value(value: Any) -> str:
    """Return a bright value for a key-value line."""
    return typer.style(str(value), fg=typer.colors.BRIGHT_WHITE)


def key_value(key: Any, val: Any, *, key_width: int = 16) -> str:
    """Format a labeled line such as ``model provider   echo``."""
    padded_key = f"{key:<{key_width}}"
    return f"{label(padded_key)} {value(val)}"


def section(title: str) -> None:
    """Print a purple section heading with a muted divider."""
    typer.echo("")
    typer.echo(text(title, bold=True))
    typer.echo(muted("-" * min(max(len(title) + 8, 58), 78)))


def banner(title: str, *, subtitle: str | None = None) -> None:
    """Print a compact purple banner."""
    width = 62
    rule = "=" * width
    typer.secho(rule, fg=PURPLE)
    typer.secho(title.center(width), fg=PURPLE, bold=True)
    if subtitle:
        typer.echo(muted(subtitle.center(width)))
    typer.secho(rule, fg=PURPLE)


def success(message: str) -> None:
    """Print an ASCII success status."""
    typer.secho(f"[ok] {message}", fg=typer.colors.GREEN, bold=True)


def warning(message: str) -> None:
    """Print an ASCII warning status."""
    typer.secho(f"[!] {message}", fg=typer.colors.YELLOW, bold=True)


def error(message: str) -> None:
    """Print an ASCII error status."""
    typer.secho(f"[x] {message}", fg=typer.colors.RED, bold=True)


def bullet(name: str, description: str) -> None:
    """Print one indented list item with a purple name and muted description."""
    typer.echo(f"  {text(name, bold=True)}  {muted(description)}")

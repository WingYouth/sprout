"""GitHub-style unified diff rendering for the Sprout CLI."""

from __future__ import annotations

import re

from rich.console import Console
from rich.text import Text

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def render_diff(path: str, diff_text: str, *, console: Console | None = None) -> None:
    """Print a file diff with change totals and old/new line numbers."""
    output = console or Console()
    lines = diff_text.splitlines()
    additions = sum(
        line.startswith("+") and not line.startswith("+++") for line in lines
    )
    deletions = sum(
        line.startswith("-") and not line.startswith("---") for line in lines
    )
    if any(line.startswith("deleted file mode") for line in lines):
        status = "D"
    elif any(line.startswith("new file mode") for line in lines):
        status = "A"
    elif any(line.startswith("rename from ") for line in lines):
        status = "R"
    else:
        status = "M"

    header = Text(f"Diff {path}  {status}  ", style="bold")
    header.append(f"+{additions}", style="bold green")
    header.append("  ")
    header.append(f"-{deletions}", style="bold red")
    output.print(header)

    old_line: int | None = None
    new_line: int | None = None
    for line in lines:
        match = _HUNK_HEADER.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            output.print(Text(line, style="cyan"))
            continue
        if line.startswith(
            (
                "+++",
                "---",
                "diff --git ",
                "index ",
                "new file mode",
                "deleted file mode",
                "rename from ",
                "rename to ",
            )
        ):
            continue
        if line.startswith("\\"):
            output.print(Text(line, style="dim"))
            continue
        if old_line is None or new_line is None or not line:
            continue

        marker, content = line[0], line[1:]
        if marker == " ":
            output.print(f" {old_line:>5} {new_line:>5} │ {content}")
            old_line += 1
            new_line += 1
        elif marker == "-":
            output.print(Text(f" {old_line:>5}       │ -{content}", style="red"))
            old_line += 1
        elif marker == "+":
            output.print(Text(f"         {new_line:>5} │ +{content}", style="green"))
            new_line += 1

    if additions == 0 and deletions == 0 and diff_text.strip():
        output.print(Text("  (no textual hunks)", style="dim"))

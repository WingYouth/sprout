"""``sprout audit`` — read, verify, and summarise the security audit stream (AUTHZ §7.3).

``verify`` is the important one: the stream is a SHA-256 hash chain, so editing,
reordering, or dropping a line makes verification fail at that line. There is
no way to "fix" a stream in place — that is the point.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.security.audit import SecurityAuditLog, audit_report, verify_chain

app = typer.Typer(
    name="audit",
    help="Inspect and verify the tamper-evident security audit stream.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _log(config: str | None) -> SecurityAuditLog:
    settings = load_settings(config)
    return SecurityAuditLog.from_settings(settings.security)


@app.command("tail")
def tail_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many entries.")] = 20,
    kind: Annotated[
        str | None, typer.Option("--kind", help="Filter on the event kind.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit raw JSON lines.")] = False,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Print the most recent audit entries."""
    log = _log(config)
    entries = log.entries()
    if kind:
        entries = [entry for entry in entries if entry.get("kind") == kind]
    if not entries:
        typer.echo(ui.muted(f"no audit entries at {log.path}"))
        return
    for entry in entries[-limit:]:
        if as_json:
            typer.echo(json.dumps(entry, ensure_ascii=False))
            continue
        typer.echo(
            f"{str(entry.get('ts', ''))[:19]}  {str(entry.get('kind', '')):<26} "
            f"{str(entry.get('decision', '') or entry.get('action', '')):<18} "
            f"{str(entry.get('actor', '') or entry.get('requested_by', '')):<12} "
            f"{str(entry.get('resource', '') or entry.get('tool', ''))}"
        )


@app.command("verify")
def verify_cmd(
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Walk the hash chain; report the first broken link, if any."""
    log = _log(config)
    result = verify_chain(log.path)
    if not Path(log.path).exists():
        typer.echo(ui.muted(f"no audit stream at {log.path}"))
        raise typer.Exit(code=0)
    if result.ok:
        ui.success(f"chain intact ({result.checked} entries)")
        if log.failures:
            ui.warning(f"{log.failures} write failure(s) recorded this session")
        return

    # Two different failures, two different messages. A foreign line is not a
    # broken link, and saying "broken at entry 0" for one sends the reader
    # looking for an edit that never happened.
    if result.foreign:
        lines = ", ".join(str(index) for index in result.foreign[:5])
        if len(result.foreign) > 5:
            lines += ", …"
        ui.error(f"{len(result.foreign)} line(s) are not audit entries: line {lines}")
        # ``ui.muted`` returns a styled string; it does not print. As a bare
        # statement this explanation was discarded, so the case it exists for —
        # reassuring the reader that the chain itself is intact — never reached
        # them and the output looked identical to a genuine break.
        typer.echo(
            ui.muted(
                f"the {result.checked} chained entries around them hash correctly; "
                "remove the stray line(s) to restore a clean chain"
            )
        )
    else:
        ui.error(f"chain broken at entry {result.broken_at}: {result.reason}")
    raise typer.Exit(code=1)


@app.command("report")
def report_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Aggregate the stream by actor, action, decision, and rule."""
    log = _log(config)
    summary = audit_report(log.entries())
    if as_json:
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    ui.banner("Security audit report", subtitle=str(log.path))
    typer.echo(ui.key_value("entries", summary["total"]))
    typer.echo(ui.key_value("denials", summary["denials"]))
    for title, key in (
        ("By decision", "by_decision"),
        ("By action", "by_action"),
        ("By actor", "by_actor"),
        ("Matched rules", "matched_rules"),
    ):
        counts = summary[key]
        if not counts:
            continue
        ui.section(title)
        for name, count in list(counts.items())[:10]:
            typer.echo(ui.key_value(name, count))

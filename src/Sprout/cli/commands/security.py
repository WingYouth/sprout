"""``sprout security``: the security and permission posture, re-checked on demand.

The CLI already answered three questions about authorization: what the engine
decided (``sprout audit``), who is waiting for a human (``sprout approvals``),
and whether the data lanes hold what was written to them (``sprout storage
check``). The one missing was the state of the boundary itself — is
authentication on, may anything run without an approval, is the SSRF guard still
refusing private addresses. ``sprout security check`` answers that from the
effective configuration, so a regression in the authorization plane shows up as
a non-zero exit code instead of as a surprise.

The checks themselves live in :mod:`Sprout.security.posture`; this module only
renders them.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING, Annotated

import typer

from Sprout.cli import ui

if TYPE_CHECKING:
    from Sprout.security.posture import PostureFinding, PostureReport

app = typer.Typer(
    name="security",
    help="Re-check the authorization and permission controls (AUTHZ_DESIGN.md).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

_WRAP_WIDTH = 88


def _render_finding(finding: PostureFinding) -> None:
    line = f"{finding.ident}  {finding.title}  ({finding.basis})"
    if finding.status == "risk":
        ui.error(line)
    elif finding.status == "warn":
        ui.warning(line)
    else:
        ui.success(line)
    for chunk in textwrap.wrap(finding.detail, width=_WRAP_WIDTH):
        typer.echo(f"    {chunk}")
    if finding.remedy:
        for chunk in textwrap.wrap(f"fix: {finding.remedy}", width=_WRAP_WIDTH):
            typer.echo(ui.muted(f"    {chunk}"))


def _render(report: PostureReport, config: str | None) -> None:
    from Sprout.security.posture import PLANES

    ui.banner("SEAM Sprout Security", subtitle="Authorization posture")
    ui.section("Configuration")
    typer.echo(ui.key_value("config", config or "<default>"))
    typer.echo(
        ui.key_value(
            "summary",
            f"{len(report.risks)} open, {len(report.warnings)} warning(s), "
            f"{report.ok_count} ok",
        )
    )
    for plane, title in PLANES:
        findings = [item for item in report.findings if item.plane == plane]
        if not findings:
            continue
        ui.section(title)
        for finding in findings:
            _render_finding(finding)

    typer.echo("")
    if report.risks:
        ui.error(
            f"{len(report.risks)} control(s) are open: "
            + ", ".join(item.ident for item in report.risks)
        )
        typer.echo(
            ui.muted(
                "    Fix them in sprout.toml, then run this check again. "
                "`sprout info` shows the effective settings."
            )
        )
        return
    ui.success(
        f"No control is open ({report.ok_count} ok, {len(_residuals(report))} known "
        f"residual(s), {len(_advisories(report))} advisory warning(s))."
    )


def _residuals(report: PostureReport) -> list[PostureFinding]:
    """Warnings that document a deliberate limitation rather than an action item."""
    from Sprout.security.posture import RESIDUAL

    return [item for item in report.warnings if item.basis == RESIDUAL]


def _advisories(report: PostureReport) -> list[PostureFinding]:
    """Warnings that point at an accepted configuration, not at a known gap."""
    from Sprout.security.posture import RESIDUAL

    return [item for item in report.warnings if item.basis != RESIDUAL]


@app.command("check")
def check(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the report as machine-readable JSON."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat warnings as failures too."),
    ] = False,
) -> None:
    """Re-check every authorization control against the effective settings.

    Each line names the review item it came from and how it was reached:

    ``live`` is an answer from the objects the runtime really builds — the
    command registry, the assembled policy engine, the SSRF guard, the git child
    environment. ``structure`` is a source or signature assertion, which is
    weaker: a rename can defeat it. ``residual`` is a limitation that was left
    open on purpose.

    Exit codes: 0 nothing is open; 1 at least one control is open, or with
    ``--strict`` at least one warning.
    """
    from Sprout.config.loader import load_settings
    from Sprout.security.posture import assess_posture

    settings = load_settings(config)
    report = assess_posture(settings, config_path=config)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        raise typer.Exit(report.status_code(strict=strict))

    _render(report, config)
    raise typer.Exit(report.status_code(strict=strict))

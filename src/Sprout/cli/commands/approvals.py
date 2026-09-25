"""``sprout approvals`` — the human decision surface for approvals (AUTHZ §5.2).

External agents can only *request* approval; deciding is reserved for a human
using the CLI or the web API. ``suggest`` reads the approval history and
proposes allowlist entries — it is read-only unless ``--apply`` is passed, and
it never proposes a destructive command class.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.security.approval import ApprovalManager, ApprovalPolicy, ApprovalStatus
from Sprout.security.layer import SecurityLayer

app = typer.Typer(
    name="approvals",
    help="List, decide, expire, and learn from pending approvals.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

#: Command families ``suggest`` will never propose, whatever the history says.
NEVER_SUGGEST = ("rm", "dd", "mkfs", "chmod", "chown", "shutdown", "reboot")


def _settings(config: str | None):
    return load_settings(config)


def _pending_manager(config: str | None) -> tuple[Any, ApprovalManager, Any]:
    """Build an ApprovalManager over the operational store without a full runtime."""
    from Sprout.storage.bundle import create_storage

    settings = _settings(config)
    bundle = create_storage(settings.storage, memory_settings=settings.memory)
    layer = SecurityLayer.from_settings(settings.security, store=bundle.operational)
    manager = layer.approvals or ApprovalManager(
        bundle.operational,
        policy=ApprovalPolicy.from_settings(settings.security),
        audit=layer.audit,
    )
    return settings, manager, bundle


def _describe(record: Any) -> str:
    age = _age(record.created_at)
    scope = record.resource_scope or "-"
    return (
        f"{record.id[:8]}  {record.status.value:<9} {record.tool:<18} "
        f"task={record.task_id[:8] or '-':<9} "
        f"session={(getattr(record, 'session_id', '') or '-')[:8]:<9} "
        f"source={record.source:<11} "
        f"scope={scope} age={age}"
    )


def _age(created_at: datetime) -> str:
    seconds = int((datetime.now(UTC) - created_at).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


@app.command("list")
def list_cmd(
    status: Annotated[
        str | None,
        typer.Option("--status", help="pending | approved | rejected | expired | consumed"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum rows to print.")] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """List approval records, pending first."""
    _, manager, bundle = _pending_manager(config)
    try:
        wanted = ApprovalStatus(status) if status else None
        records = asyncio.run(manager.store.list_approvals(wanted))
        if as_json:
            typer.echo(
                json.dumps([_record_dict(record) for record in records[:limit]], indent=2)
            )
            return
        ui.banner("Approvals", subtitle=f"{len(records)} record(s)")
        if not records:
            typer.echo(ui.muted("nothing to show"))
            return
        for record in records[:limit]:
            typer.echo(_describe(record))
    finally:
        asyncio.run(bundle.close())


@app.command("sweep")
def sweep_cmd(
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Turn stale PENDING approvals into EXPIRED so tasks can be retried."""
    _, manager, bundle = _pending_manager(config)
    try:
        swept = asyncio.run(manager.sweep_expired())
        age = asyncio.run(manager.oldest_pending_age())
        typer.echo(ui.muted(f"swept {swept} expired record(s)"))
        if age is not None:
            typer.echo(ui.key_value("oldest pending", f"{int(age)}s"))
    finally:
        asyncio.run(bundle.close())


@app.command("approve")
def approve_cmd(
    approval_id: Annotated[str, typer.Argument(help="Approval id (prefix is enough).")],
    by: Annotated[str, typer.Option("--by", help="Who is deciding.")] = "cli",
    reason: Annotated[str | None, typer.Option("--reason", help="Decision note.")] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--no-resume",
            help="Continue the task this grant was blocking (default; needs a full runtime).",
        ),
    ] = True,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Approve one request and continue whatever it was blocking."""
    _decide(approval_id, True, by=by, reason=reason, resume=resume, config=config)


@app.command("reject")
def reject_cmd(
    approval_id: Annotated[str, typer.Argument(help="Approval id (prefix is enough).")],
    by: Annotated[str, typer.Option("--by", help="Who is deciding.")] = "cli",
    reason: Annotated[str | None, typer.Option("--reason", help="Decision note.")] = None,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Reject one request."""
    _decide(approval_id, False, by=by, reason=reason, resume=False, config=config)


@app.command("resume")
def resume_cmd(
    session_id: Annotated[str, typer.Argument(help="Session id to resume.")],
    user: Annotated[str, typer.Option("--user", help="Identity recorded on turns.")] = "cli-user",
    content: Annotated[
        str, typer.Option("--content", help="Instruction to continue with.")
    ] = "Continue",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Resume a session that paused waiting for approval."""
    from Sprout.runtime.factory import create_runtime

    runtime = create_runtime(_settings(config))

    async def run() -> Any:
        return await runtime.resume_pending(
            session_id,
            user_id=user,
            content=content,
        )

    outbound = asyncio.run(run())
    typer.echo(outbound.content)


@app.command("suggest")
def suggest_cmd(
    apply_changes: Annotated[
        bool, typer.Option("--apply", help="Write the suggestion into sprout.toml.")
    ] = False,
    config: Annotated[str | None, typer.Option("--config", help="Path to sprout.toml.")] = None,
) -> None:
    """Propose allowlist entries from approval history (read-only unless --apply)."""
    settings, manager, bundle = _pending_manager(config)
    try:
        suggestions = asyncio.run(manager.suggest_allowlist())
    finally:
        asyncio.run(bundle.close())
    safe = [item for item in suggestions if not _is_destructive(str(item["tool"]))]
    if not safe:
        typer.echo(ui.muted("no allowlist suggestions"))
        return

    # Only a name recovered from a real argv can go in the allowlist; a tool
    # name (``cli_tool_run``) matches no command and would be written as an
    # entry that never fires.
    actionable = [item for item in safe if item.get("actionable")]
    names = [str(item["tool"]) for item in actionable]

    ui.banner("Allowlist suggestions", subtitle=f"{len(names)} candidate(s)")
    for item in actionable:
        typer.echo(ui.key_value(str(item["tool"]), f"{item['approvals']} approval(s)"))
    unactionable = [item for item in safe if not item.get("actionable")]
    if unactionable:
        # Say so rather than dropping them: an operator seeing their most
        # frequent approval missing from the list deserves to know why.
        typer.echo("")
        typer.echo(
            ui.muted(
                "not proposeable (tool names, not commands — [security.commands] "
                "is keyed on argv[0]):"
            )
        )
        for item in unactionable:
            typer.echo(
                ui.key_value(str(item["tool"]), f"{item['approvals']} approval(s)")
            )

    if not apply_changes:
        typer.echo("")
        typer.echo(ui.muted("read-only; pass --apply to write [security.commands]"))
        return
    if not names:
        typer.echo("")
        typer.echo(ui.muted("nothing to apply"))
        return
    target = Path(config) if config else Path("sprout.toml")
    if not target.is_file():
        raise typer.BadParameter(f"No configuration file to update: {target}")
    updated = apply_allowlist(target.read_text(encoding="utf-8"), names, settings)
    target.write_text(updated, encoding="utf-8")
    ui.success(f"updated {target}")


def _decide(
    approval_id: str,
    approved: bool,
    *,
    by: str,
    reason: str | None,
    resume: bool,
    config: str | None,
) -> None:
    if resume:
        from Sprout.runtime.factory import create_runtime

        runtime = create_runtime(_settings(config))

        async def run() -> tuple[Any, str]:
            record = await _resolve(runtime, approval_id)
            # ``decide_approval`` records the decision *and* continues the task
            # it was blocking, so the grant is never left unused.
            decided = await runtime.decide_approval(
                record.id, approved, decided_by=by, reason=reason, channel="cli"
            )
            return decided, await _task_status(runtime, decided)

        # No ``runtime.stop()``: the process is about to exit, and the storage
        # handles are process-shared with a refcount — closing them here would
        # take the database out from under any other runtime in this process.
        record, task_status = asyncio.run(run())
    else:
        _, manager, bundle = _pending_manager(config)

        async def run_simple() -> Any:
            resolved = await _resolve_manager(manager, approval_id)
            return await manager.decide(
                resolved.id, approved, decided_by=by, reason=reason, channel="cli"
            )

        try:
            record = asyncio.run(run_simple())
        finally:
            asyncio.run(bundle.close())
        task_status = ""
    if record.status is ApprovalStatus.APPROVED:
        ui.success(f"approved {record.id[:8]}")
        if task_status:
            typer.echo(ui.muted(f"task {record.task_id[:8]} is now {task_status}"))
    elif record.status is ApprovalStatus.REJECTED:
        ui.warning(f"rejected {record.id[:8]}")
    else:
        ui.warning(f"{record.status.value} {record.id[:8]}: {record.reason or ''}")


async def _task_status(runtime: Any, record: Any) -> str:
    """How the task the grant unblocked ended up, if it has one.

    A granted verification resumes the graph, which then parks again one layer
    up on the change proposal. Saying so beats printing ``approved`` and leaving
    the operator to discover the second gate by polling ``project changes``.
    """
    if not record.task_id:
        return ""
    task = await runtime.get_task(record.task_id)
    return task.status.value if task is not None else ""


async def _resolve(runtime: Any, prefix: str) -> Any:
    return await _resolve_manager(runtime.approvals, prefix)


async def _resolve_manager(manager: ApprovalManager, prefix: str) -> Any:
    record = await manager.store.get_approval(prefix)
    if record is not None:
        return record
    for candidate in await manager.store.list_approvals():
        if candidate.id.startswith(prefix):
            return candidate
    raise typer.BadParameter(f"Approval not found: {prefix}")


def _record_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "tool": record.tool,
        "status": record.status.value,
        "task_id": record.task_id,
        "source": record.source,
        "resource_scope": record.resource_scope,
        "requested_by": record.requested_by,
        "decided_by": record.decided_by,
        "created_at": record.created_at.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


def _is_destructive(tool: str) -> bool:
    name = re.split(r"[\\/]", tool)[-1].split()[0].casefold() if tool.strip() else ""
    return name in NEVER_SUGGEST


def apply_allowlist(text: str, names: list[str], settings: Any) -> str:
    """Merge ``names`` into the ``[security.commands] allowlist`` of a TOML file."""
    existing = list(settings.security.commands.allowlist)
    merged = sorted({*existing, *names})
    rendered = "allowlist = [" + ", ".join(f'"{name}"' for name in merged) + "]"
    if "[security.commands]" in text:
        pattern = re.compile(r"(?m)^\s*allowlist\s*=\s*\[[^\]]*\]")
        if pattern.search(text):
            return pattern.sub(rendered, text, count=1)
        return _insert_after_section(text, "[security.commands]", rendered)
    return text.rstrip("\n") + f"\n\n[security.commands]\n{rendered}\n"


def _insert_after_section(text: str, header: str, line: str) -> str:
    lines = text.splitlines()
    for index, existing in enumerate(lines):
        if existing.strip() == header:
            lines.insert(index + 1, line)
            break
    return "\n".join(lines) + "\n"

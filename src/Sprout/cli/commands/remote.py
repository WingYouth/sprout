"""``sprout remote``: operate a remote SEMA service over RPC."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from Sprout.gateway.rpc_client import RPCClient

app = typer.Typer(help="Remote SEMA operations over HTTP/RPC.", no_args_is_help=True)


def _client(url: str, token: str | None) -> RPCClient:
    return RPCClient(url, token=token)


def _run(coro):
    return asyncio.run(coro)


@app.command("workspace-open")
def workspace_open(
    path: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Open a workspace on the remote daemon."""
    typer.echo(_run(_client(url, token).call("workspace.open", {"path": path})))


@app.command("workspace-list")
def workspace_list(
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """List remote workspaces."""
    typer.echo(_run(_client(url, token).call("workspace.list", {})))


@app.command("task-create")
def task_create(
    workspace_id: Annotated[str, typer.Argument()],
    instruction: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Create a task on the remote daemon."""
    typer.echo(
        _run(
            _client(url, token).call(
                "task.create",
                {"workspace_id": workspace_id, "instruction": instruction},
            )
        )
    )


@app.command("task-run")
def task_run(
    task_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Run a task on the remote daemon."""
    typer.echo(_run(_client(url, token).call("task.run", {"task_id": task_id})))


@app.command("task-submit")
def task_submit(
    task_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Submit a task to the remote worker queue."""
    typer.echo(_run(_client(url, token).call("task.submit", {"task_id": task_id})))


@app.command("task-changes")
def task_changes(
    task_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """List change proposals for a task."""
    typer.echo(_run(_client(url, token).call("task.changes", {"task_id": task_id})))


@app.command("proposal-show")
def proposal_show(
    proposal_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Show a change proposal."""
    typer.echo(
        _run(
            _client(url, token).call(
                "proposal.show",
                {"proposal_id": proposal_id},
            )
        )
    )


@app.command("proposal-approve")
def proposal_approve(
    proposal_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Approve a proposal."""
    typer.echo(
        _run(
            _client(url, token).call(
                "proposal.approve",
                {"proposal_id": proposal_id},
            )
        )
    )


@app.command("proposal-reject")
def proposal_reject(
    proposal_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Reject a proposal."""
    typer.echo(
        _run(
            _client(url, token).call(
                "proposal.reject",
                {"proposal_id": proposal_id, "reason": ""},
            )
        )
    )


@app.command("proposal-apply")
def proposal_apply(
    proposal_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Apply a proposal."""
    typer.echo(
        _run(
            _client(url, token).call(
                "proposal.apply",
                {"proposal_id": proposal_id},
            )
        )
    )


@app.command("proposal-rollback")
def proposal_rollback(
    proposal_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Roll back a proposal."""
    typer.echo(
        _run(
            _client(url, token).call(
                "proposal.rollback",
                {"proposal_id": proposal_id},
            )
        )
    )


@app.command("trajectory-query")
def trajectory_query(
    task_id: Annotated[str, typer.Argument()],
    url: Annotated[str, typer.Option("--url")] = "http://127.0.0.1:8000",
    token: Annotated[str | None, typer.Option("--token")] = None,
) -> None:
    """Query trajectory events."""
    typer.echo(
        _run(
            _client(url, token).call(
                "trajectory.query",
                {"task_id": task_id},
            )
        )
    )

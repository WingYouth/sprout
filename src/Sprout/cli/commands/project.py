"""``sprout project``: operate the Project Agent Runtime."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.cli.diff import render_diff

app = typer.Typer(help="Project Agent Runtime operations.", no_args_is_help=True)


def _gateway(config: str | None):
    from Sprout.config.loader import load_settings
    from Sprout.gateway.project_gateway import ProjectGateway
    from Sprout.runtime.factory import create_runtime

    runtime = create_runtime(load_settings(config))
    return ProjectGateway(runtime, transport="cli", default_user="cli-user")


def _run(coro):
    return asyncio.run(coro)


async def _resolve_proposal(gateway, prefix: str):
    try:
        return await gateway.find_proposal(prefix)
    except LookupError:
        raise typer.BadParameter(
            f"No change proposal matches id prefix {prefix!r}"
        ) from None


@app.command("workspace")
def workspace(
    path: Annotated[str, typer.Argument(help="Workspace path.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Open and register a local or Git workspace."""
    gateway = _gateway(config)

    async def run() -> None:
        opened = await gateway.open_workspace(path)
        typer.echo(f"{opened.id}  {opened.kind.value}  {opened.root}")

    _run(run())


@app.command("analyze")
def analyze(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the analysis as machine-readable JSON."),
    ] = False,
) -> None:
    """Analyze a workspace and persist its project knowledge."""
    gateway = _gateway(config)

    async def run() -> None:
        analysis = await gateway.analyze_workspace(workspace_id)
        payload = {
            "workspace_id": analysis.workspace.id,
            "languages": list(analysis.manifest.detected_languages),
            "framework_hints": list(analysis.manifest.framework_hints),
            "entry_points": list(analysis.manifest.entry_points),
            "test_commands": list(analysis.manifest.test_commands),
            "build_commands": list(analysis.manifest.build_commands),
            "resources": len(analysis.read_plan.resources),
            "graph_nodes": len(analysis.graph.nodes),
            "graph_edges": len(analysis.graph.edges),
            "knowledge_items": len(analysis.knowledge.items),
        }
        if as_json:
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        ui.banner("Workspace Intelligence", subtitle=analysis.workspace.id)
        ui.section("Manifest")
        languages = ", ".join(analysis.manifest.detected_languages) or "-"
        typer.echo(ui.key_value("languages", languages))
        typer.echo(ui.key_value("frameworks", ", ".join(analysis.manifest.framework_hints) or "-"))
        typer.echo(ui.key_value("entry points", ", ".join(analysis.manifest.entry_points) or "-"))
        ui.section("Read Plan")
        typer.echo(ui.key_value("resources", len(analysis.read_plan.resources)))
        ui.section("Graph")
        typer.echo(ui.key_value("nodes", len(analysis.graph.nodes)))
        typer.echo(ui.key_value("edges", len(analysis.graph.edges)))
        ui.section("Knowledge")
        typer.echo(ui.key_value("items", len(analysis.knowledge.items)))

    _run(run())


@app.command("graph")
def graph(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    name: Annotated[
        str,
        typer.Option(
            "--name", help="Node name, qualified name, file path, or id to inspect."
        ),
    ] = "",
    relation: Annotated[
        str | None,
        typer.Option("--relation", help="Filter edges by relation."),
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the query result as JSON."),
    ] = False,
) -> None:
    """Query the read-only Workspace Graph."""
    gateway = _gateway(config)

    async def run() -> None:
        result = await gateway.query_workspace_graph(
            workspace_id,
            name=name,
            relation=relation,
        )
        if as_json:
            payload = {
                "nodes": [
                    {
                        "id": node.id,
                        "kind": node.kind,
                        "name": node.name,
                        "qualified_name": node.qualified_name,
                    }
                    for node in result.nodes
                ],
                "edges": [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "relation": edge.relation,
                    }
                    for edge in result.edges
                ],
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        ui.banner("Workspace Graph Query", subtitle=workspace_id)
        typer.echo(ui.key_value("nodes", len(result.nodes)))
        typer.echo(ui.key_value("edges", len(result.edges)))
        for edge in result.edges[:20]:
            typer.echo(f"  {edge.relation}: {edge.source} -> {edge.target}")

    _run(run())


def _node_payload(node) -> dict:
    """JSON shape shared by the read-only graph commands."""
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "path": node.resource.path if node.resource is not None else None,
        "line": node.line,
    }


def _edge_payload(edge) -> dict:
    return {"source": edge.source, "target": edge.target, "relation": edge.relation}


def _edge_lines(nodes, edges, *, limit: int = 20) -> list[str]:
    """Render edges by node name where the node is in scope, id otherwise."""
    names = {node.id: node.qualified_name or node.name or node.id for node in nodes}
    return [
        f"  {edge.relation}: {names.get(edge.source, edge.source)} "
        f"-> {names.get(edge.target, edge.target)}"
        for edge in edges[:limit]
    ]


@app.command("workspaces")
def workspaces(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the workspace list as machine-readable JSON."),
    ] = False,
) -> None:
    """List every registered workspace as ``id  kind  root``."""
    gateway = _gateway(config)

    async def run() -> None:
        items = await gateway.list_workspaces()
        if as_json:
            typer.echo(
                json.dumps(
                    [
                        {"id": item.id, "kind": item.kind.value, "root": str(item.root)}
                        for item in items
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        ui.banner("Workspaces", subtitle=f"{len(items)} workspace(s)")
        if not items:
            typer.echo(ui.muted("No workspace has been opened yet."))
            return
        for item in items:
            typer.echo(f"{item.id}  {item.kind.value}  {item.root}")

    _run(run())


@app.command("symbols")
def symbols(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Filter by node kind: class, function, method, or test."),
    ] = None,
    query: Annotated[
        str,
        typer.Option("--query", help="Case-insensitive filter on name or qualified name."),
    ] = "",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the symbols as machine-readable JSON."),
    ] = False,
) -> None:
    """List the classes, functions, methods, and tests of a workspace."""
    gateway = _gateway(config)

    async def run() -> None:
        nodes = await gateway.query_workspace_symbols(workspace_id, kind=kind, query=query)
        if as_json:
            typer.echo(
                json.dumps(
                    [_node_payload(node) for node in nodes], indent=2, ensure_ascii=False
                )
            )
            return
        ui.banner("Workspace Symbols", subtitle=workspace_id)
        typer.echo(ui.key_value("symbols", len(nodes)))
        for node in nodes[:40]:
            location = node.resource.path if node.resource is not None else "-"
            typer.echo(f"  [{node.kind}] {node.qualified_name or node.name}  ({location})")

    _run(run())


@app.command("dependencies")
def dependencies(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    path: Annotated[
        str,
        typer.Argument(
            help="File path: workspace-relative, or the absolute resource path."
        ),
    ],
    direction: Annotated[
        str,
        typer.Option("--direction", help="out (imports), in (imported by), or both."),
    ] = "out",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the dependency edges as JSON."),
    ] = False,
) -> None:
    """Trace one file's dependencies, or who depends on it."""
    gateway = _gateway(config)

    async def run() -> None:
        result = await gateway.query_workspace_dependencies(
            workspace_id, path, direction=direction
        )
        if as_json:
            payload = {
                "path": path,
                "direction": direction,
                "nodes": [_node_payload(node) for node in result.nodes],
                "edges": [_edge_payload(edge) for edge in result.edges],
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        ui.banner("File Dependencies", subtitle=f"{path} ({direction})")
        typer.echo(ui.key_value("edges", len(result.edges)))
        for line in _edge_lines(result.nodes, result.edges):
            typer.echo(line)

    _run(run())


@app.command("subgraph")
def subgraph(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    name: Annotated[
        str,
        typer.Option(
            "--name",
            help="Node id, name, qualified name, or file path to start from.",
        ),
    ],
    depth: Annotated[
        int, typer.Option("--depth", help="How many hops to walk.")
    ] = 2,
    relation: Annotated[
        str | None,
        typer.Option("--relation", help="Restrict the walk to one relation."),
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the subgraph as machine-readable JSON."),
    ] = False,
) -> None:
    """Walk out from one node and return its neighbourhood."""
    gateway = _gateway(config)

    async def run() -> None:
        result = await gateway.query_workspace_subgraph(
            workspace_id, name, max_depth=depth, relation=relation
        )
        if as_json:
            payload = {
                "name": name,
                "depth": depth,
                "nodes": [_node_payload(node) for node in result.nodes],
                "edges": [_edge_payload(edge) for edge in result.edges],
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        ui.banner("Workspace Subgraph", subtitle=f"{name} (depth {depth})")
        typer.echo(ui.key_value("nodes", len(result.nodes)))
        typer.echo(ui.key_value("edges", len(result.edges)))
        for line in _edge_lines(result.nodes, result.edges, limit=30):
            typer.echo(line)

    _run(run())


@app.command("knowledge")
def knowledge(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    query: Annotated[
        str,
        typer.Option("--query", help="Case-insensitive text filter."),
    ] = "",
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="fact or inference."),
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the query result as JSON."),
    ] = False,
) -> None:
    """Query read-only Project Knowledge."""
    gateway = _gateway(config)

    async def run() -> None:
        items = await gateway.query_project_knowledge(
            workspace_id,
            query=query,
            kind=kind,
        )
        if as_json:
            typer.echo(
                json.dumps(
                    [
                        {
                            "id": item.id,
                            "kind": item.kind,
                            "statement": item.statement,
                            "confidence": item.confidence,
                            "evidence_ids": list(item.evidence_ids),
                        }
                        for item in items
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        ui.banner("Project Knowledge", subtitle=workspace_id)
        typer.echo(ui.key_value("items", len(items)))
        for item in items[:20]:
            typer.echo(f"  [{item.kind}] {item.statement}")

    _run(run())


@app.command("readplan")
def readplan(
    task_id: Annotated[str, typer.Argument(help="Task id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the read plan as machine-readable JSON."),
    ] = False,
) -> None:
    """Build the bounded read plan for a task."""
    gateway = _gateway(config)

    async def run() -> None:
        plan = await gateway.plan_task(task_id)
        if as_json:
            payload = {
                "id": plan.id,
                "task_id": plan.task_id,
                "purpose": plan.purpose,
                "stage": plan.stage.value,
                "excludes": list(plan.excludes),
                "resources": [
                    {"path": resource.path, "kind": resource.kind.value}
                    for resource in plan.resources
                ],
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        ui.banner("Task Read Plan", subtitle=task_id)
        typer.echo(ui.key_value("stage", plan.stage.value))
        typer.echo(ui.key_value("purpose", plan.purpose or "-"))
        typer.echo(ui.key_value("resources", len(plan.resources)))
        for resource in plan.resources[:20]:
            typer.echo(f"  [{resource.kind.value}] {resource.path}")

    _run(run())


@app.command("task-create")
def task_create(
    workspace_id: Annotated[str, typer.Argument(help="Workspace id.")],
    instruction: Annotated[str, typer.Argument(help="Task instruction.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Create a project task."""
    gateway = _gateway(config)

    async def run() -> None:
        task = await gateway.create_task(workspace_id, instruction)
        typer.echo(task.id)

    _run(run())


@app.command("task-run")
def task_run(
    task_id: Annotated[str, typer.Argument(help="Task id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Run a project task through the execution graph."""
    gateway = _gateway(config)

    async def run() -> None:
        result = await gateway.run_task(task_id)
        typer.echo(f"{result.task_id}  {result.status}")

    _run(run())


@app.command("task-cancel")
def task_cancel(
    task_id: Annotated[str, typer.Argument(help="Task id or prefix.")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Why it is being cancelled.")
    ] = None,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Cancel a task that is parked waiting on a human, or still running.

    Leaves the task row and everything that cites it in place, so the audit
    trail survives; the status becomes ``cancelled``.
    """
    gateway = _gateway(config)

    async def run() -> None:
        # A prefix is accepted because task ids are printed truncated in most
        # surfaces; the gateway refuses an ambiguous one rather than guessing.
        try:
            cancelled = await gateway.cancel_task(task_id, reason=reason or "")
        except LookupError as exc:
            raise typer.BadParameter(str(exc)) from None
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from None
        ui.success(f"cancelled {cancelled.id}")
        typer.echo(ui.key_value("status", cancelled.status.value))

    _run(run())


@app.command("changes")
def changes(
    task_id: Annotated[str, typer.Argument(help="Task id.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """List change proposals for a task."""
    gateway = _gateway(config)

    async def run() -> None:
        proposals = await gateway.list_changes(task_id)
        if not proposals:
            typer.echo("No change proposals.")
            return
        for proposal in proposals:
            typer.echo(
                f"[{proposal.status.value:>7}] {proposal.id[:8]} "
                f"risk={proposal.risk} files={len(proposal.files_changed)}"
            )

    _run(run())


@app.command("apply")
def apply(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id or prefix.")],
    allow_failing_tests: Annotated[
        bool,
        typer.Option(
            "--allow-failing-tests",
            help="Land the change even when its verification commands failed.",
        ),
    ] = False,
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Apply an already approved change proposal."""
    gateway = _gateway(config)

    async def run() -> None:
        proposal = await _resolve_proposal(gateway, proposal_id)
        result = await gateway.apply_proposal(
            proposal.id,
            allow_failing_tests=allow_failing_tests,
        )
        typer.echo(f"applied={result.applied}  {result.reason}")

    _run(run())


@app.command("show")
def show(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id or prefix.")],
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show proposal details and diff."""
    gateway = _gateway(config)

    async def run() -> None:
        proposal = await _resolve_proposal(gateway, proposal_id)
        typer.echo(f"Proposal : {proposal.id}")
        typer.echo(f"Task     : {proposal.task_id}")
        typer.echo(f"Status   : {proposal.status.value}")
        typer.echo(f"Risk     : {proposal.risk}")
        typer.echo(f"Files    : {', '.join(proposal.files_changed) or '-'}")
        for diff in proposal.diffs:
            render_diff(diff.path, diff.diff_text)

    _run(run())


@app.command("approve")
def approve(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id or prefix.")],
    by: Annotated[str, typer.Option("--by", help="Approver identity.")] = "cli",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Approve a pending change proposal and resume the task's APPLY node."""
    gateway = _gateway(config)

    async def run() -> None:
        proposal = await _resolve_proposal(gateway, proposal_id)
        updated = await gateway.approve_proposal(proposal.id)
        typer.echo(f"approved={updated.status.value}")

    _run(run())


@app.command("reject")
def reject(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id or prefix.")],
    reason: Annotated[str, typer.Option("--reason", help="Rejection reason.")] = "",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Reject a pending change proposal."""
    gateway = _gateway(config)

    async def run() -> None:
        proposal = await _resolve_proposal(gateway, proposal_id)
        updated = await gateway.reject_proposal(proposal.id, reason=reason)
        typer.echo(f"rejected={updated.status.value}")

    _run(run())


@app.command("rollback")
def rollback(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id or prefix.")],
    by: Annotated[str, typer.Option("--by", help="Approver identity.")] = "cli",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Roll back an applied change proposal."""
    gateway = _gateway(config)

    async def run() -> None:
        proposal = await _resolve_proposal(gateway, proposal_id)
        result = await gateway.rollback_proposal(proposal.id)
        typer.echo(f"applied={result.applied}  {result.reason}")

    _run(run())

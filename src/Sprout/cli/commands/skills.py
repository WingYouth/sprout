"""``sprout skills`` — list, search, and install skills (design §7.4/§11).

Installing goes through :class:`~Sprout.skills.broker.SkillInstallBroker`, so it
is subject to the same policy engine and approval flow as every other action: the
CLI never installs anything the policy would not allow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.config.settings import Settings
from Sprout.security.approval import ApprovalManager, ApprovalPolicy
from Sprout.skills.broker import SkillInstallBroker
from Sprout.skills.index import SkillIndex, reconcile
from Sprout.skills.layout import index_path
from Sprout.skills.resolver import SkillResolver
from Sprout.skills.sources.base import SkillSource
from Sprout.skills.sources.catalog import CatalogSource
from Sprout.skills.sources.cli import CliRunner, NetworkBrokerRunner, ProcessBrokerRunner
from Sprout.skills.sources.github import GitHubSource
from Sprout.skills.sources.local import LocalDirSource
from Sprout.skills.sources.url import UrlSource
from Sprout.skills.sources.wellknown import WellKnownSource

app = typer.Typer(
    name="skills",
    help="List, search, and install skills.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

ConfigOption = Annotated[str | None, typer.Option("--config", "-c", help="Config file to load.")]
DirOption = Annotated[str | None, typer.Option("--dir", "-d", help="Skills directory.")]
ManifestOption = Annotated[str | None, typer.Option("--manifest", "-m", help="Catalog manifest.")]


def _skills_dir(directory: str | None, settings: Settings) -> Path:
    """``--dir`` wins; otherwise the configured ``settings.skills_dir`` (§11)."""
    return Path(directory).expanduser() if directory else Path(settings.skills_dir)


#: Sources that read from a local directory rather than the network, so
#: ``install --source <one of these>`` needs ``--from`` to know which directory.
_LOCAL_SOURCES = frozenset({"local", "project", "evolved"})

#: ``--source`` name -> CLI-backed source (design §7.3). These fetch with the
#: machine's own ``git``/``curl``; nothing is installed here (§7.4).
_CLI_SOURCES: dict[str, type] = {
    "github": GitHubSource,
    "url": UrlSource,
    "well-known": WellKnownSource,
    "wellknown": WellKnownSource,  # tolerated spelling of ``WellKnownSource.name``
}


def _workspace_for_cwd() -> Any:
    """Minimal :class:`Workspace` rooted at the current directory."""
    from Sprout.workspace.models import Workspace, WorkspaceKind

    root = Path.cwd().resolve()
    kind = (
        WorkspaceKind.GIT_REPOSITORY
        if (root / ".git").exists()
        else WorkspaceKind.LOCAL_DIRECTORY
    )
    return Workspace(id="", root=root, kind=kind)


def _build_runner(
    settings: Settings, *, source: str, via_broker: bool, layer: Any = None
) -> CliRunner | None:
    """A broker-backed runner for ``--via-broker``, otherwise ``None``.

    ``None`` is the default on purpose: a human running ``sprout skills`` *is* the
    operator, so the source's own :class:`SubprocessRunner` fetches directly.

    ``--via-broker`` picks the broker that matches the wire protocol. ``github``
    shells out to ``git``, so it goes through :class:`~Sprout.execution.ProcessBroker`
    — audited, and approval-gated because ``git`` is allowlisted but not auto-run.
    ``url``/``well-known`` only issue an HTTP ``GET``, so they go through
    :class:`~Sprout.execution.NetworkBroker`, where ``network.get`` is ``ALLOW``
    and :class:`NetworkGuard` refuses SSRF targets.
    """
    if not via_broker:
        return None
    from Sprout.security.layer import SecurityLayer
    from Sprout.storage.bundle import create_storage

    if layer is None:
        storage = create_storage(settings.storage, memory_settings=settings.memory)
        layer = SecurityLayer.from_settings(settings.security, store=storage.operational)
    workspace = _workspace_for_cwd()

    if source == "github":
        from Sprout.execution.process_broker import ProcessBroker

        process = ProcessBroker(
            layer.policy_engine,
            commands=layer.commands,
            secrets=layer.secrets,
            audit=layer.audit,
            extra_env_names=layer.extra_env_names,
        )
        return ProcessBrokerRunner(process, workspace)

    from Sprout.execution.network_broker import NetworkBroker

    network = NetworkBroker(
        layer.policy_engine,
        approvals=layer.approvals,
        guard=layer.guard,
        secrets=layer.secrets,
        audit=layer.audit,
    )
    return NetworkBrokerRunner(network, workspace)


def _build_source(
    source: str,
    *,
    manifest: str | None,
    directory: str | None,
    settings: Settings,
    runner: CliRunner | None = None,
) -> SkillSource:
    if source == "catalog":
        if not manifest:
            raise typer.BadParameter("--manifest is required for the catalog source")
        return CatalogSource(manifest)
    if source in _CLI_SOURCES:
        return _CLI_SOURCES[source](runner=runner)
    return LocalDirSource(_skills_dir(directory, settings), source=source)


def _build_crawl_source(settings: Settings, skills_dir: Path) -> Any:
    """The discovery source, honouring any operator overrides in settings."""
    from Sprout.skills.sources.crawl import build_crawl_source

    skills = settings.skills
    return build_crawl_source(
        skills_dir,
        skills.catalog_sites,
        max_results=skills.crawl_max_results,
        timeout=skills.crawl_timeout,
        seeds=tuple(skills.marketplace_seeds) or None,
        awesome=tuple(skills.marketplace_awesome) or None,
        topics=tuple(skills.marketplace_topics) or None,
    )


def _installable_source(settings: Settings, skills_dir: Path) -> Any:
    """Where ``skills install <name>`` looks a name up.

    The discovered cache answers by *name*, which is what a user has after
    ``skills find``; ``--source github`` instead treats the argument as an
    ``owner/repo[/path]`` locator (design §12), so the two are separate paths.
    """
    return _build_crawl_source(settings, skills_dir)


def _cli_call(awaitable: Any, *, action: str) -> Any:
    """Await a source/broker call, turning expected failures into a clean exit.

    A broker-routed fetch can be refused by policy (``git``/``curl`` are not in
    ``auto_run``, so ``PROCESS_RUN`` becomes ``REQUIRE_APPROVAL`` and
    :class:`ProcessBrokerRunner` raises). A source can also reject its argument —
    ``--source github`` wants an ``owner/repo`` locator, so a bare skill name is a
    usage error rather than a crash. Report both instead of a traceback.
    """
    try:
        return asyncio.run(awaitable)
    except PermissionError as exc:
        ui.error(f"Policy denied {action}: {exc}")
        raise typer.Exit(code=1) from exc
    except (ValueError, RuntimeError) as exc:
        ui.error(f"Cannot {action}: {exc}")
        raise typer.Exit(code=1) from exc


@app.command("list")
def list_skills(config: ConfigOption = None, directory: DirOption = None) -> None:
    """Show the skill registry (names and summaries only).

    A registry row whose files are gone is marked ``[missing]`` rather than
    listed as if it were installed. That distinction was invisible before: the
    registry showed three skills while the tree held one, and the only command
    that could tell you — ``index --rebuild`` — silently rewrote the snapshot
    instead.
    """
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    if directory:
        # An explicit --dir points at a standalone tree: read its own snapshot.
        records = SkillIndex(index_path(_skills_dir(directory, settings))).list()
        missing = {record.name for record in records if not _artifact_present(record)}
    else:
        storage = create_storage(settings.storage, memory_settings=settings.memory)
        records = asyncio.run(storage.skills.list()) if storage.skills else []
        missing = {record.name for record in records if not _artifact_present(record)}
    if not records:
        ui.warning(
            "No skills indexed. Run `sprout skills index --rebuild` to scan the directory."
        )
        return
    ui.section(f"Skills ({len(records)})")
    groups: dict[tuple[str, ...], list[Any]] = {}
    for record in records:
        groups.setdefault(tuple(record.menu_path), []).append(record)
    for menu_path, group in sorted(groups.items(), key=lambda item: item[0]):
        if menu_path:
            ui.section(" / ".join(menu_path))
        for record in sorted(group, key=lambda item: item.name):
            if record.name in missing:
                ui.error(
                    f"{record.name} [{record.trust}] [missing] the recorded path is gone: "
                    f"{record.path or '(none)'}"
                )
                continue
            ui.bullet(f"{record.name} [{record.trust}]", record.description or record.version)
    if missing:
        ui.warning(
            f"{len(missing)} skill(s) are registered but absent from disk. "
            "Run `sprout skills index --rebuild` to sync the snapshot, or "
            "`sprout skills forget <name>` to drop the registry row."
        )


@app.command("menu")
def skill_menu(config: ConfigOption = None, directory: DirOption = None) -> None:
    """Enter the database-backed hierarchical Skill menu."""
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    if directory:
        records = SkillIndex(index_path(skills_dir)).list()
    else:
        storage = create_storage(settings.storage, memory_settings=settings.memory)
        records = asyncio.run(storage.skills.list()) if storage.skills else []
    if not records:
        ui.warning("No skills indexed. Run `sprout skills index --rebuild` first.")
        return

    prefix: tuple[str, ...] = ()
    while True:
        directories = sorted(
            {
                record.menu_path[len(prefix)]
                for record in records
                if record.menu_path[: len(prefix)] == prefix
                and len(record.menu_path) > len(prefix)
            }
        )
        leaves = sorted(
            (record for record in records if record.menu_path == prefix),
            key=lambda record: record.name,
        )
        choices = [
            questionary.Choice(f"{name}/", value=("directory", name))
            for name in directories
        ]
        choices.extend(
            questionary.Choice(
                f"{record.name} [{record.trust}]",
                value=("skill", record),
            )
            for record in leaves
        )
        if prefix:
            choices.append(questionary.Choice("done  返回上一级", value=("back", None)))
        choices.append(questionary.Choice("done  退出 Skill 菜单", value=("exit", None)))
        selected = questionary.select(
            f"Skill / {' / '.join(prefix) if prefix else '根目录'}",
            choices=choices,
        ).ask()
        if selected is None or selected[0] == "exit":
            return
        if selected[0] == "back":
            prefix = prefix[:-1]
            continue
        if selected[0] == "directory":
            prefix = (*prefix, selected[1])
            continue
        record = selected[1]
        ui.section(record.name)
        ui.bullet("路径", record.path or "(none)")
        ui.bullet("描述", record.description or record.version)
        if not questionary.confirm("继续浏览 Skill 菜单？", default=True).ask():
            return


def _artifact_present(record: Any) -> bool:
    """True when a registry row's recorded artifact still exists on disk.

    A row with no ``path`` is treated as present: nothing recorded where it
    lives, so absence cannot be proven, and guessing "missing" would flag rows
    the operator cannot act on.
    """
    if not record.path:
        return True
    return Path(record.path).exists()


@app.command("search")
def search_skills(
    query: str,
    source: Annotated[str, typer.Option("--source", "-s", help="Source to search.")] = "local",
    manifest: ManifestOption = None,
    directory: DirOption = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max hits.")] = 10,
    via_broker: Annotated[
        bool, typer.Option("--via-broker", help="Route git/curl through the policy broker.")
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Search a source. Read-only: nothing is fetched or installed."""
    settings = load_settings(config)
    runner = _build_runner(settings, source=source, via_broker=via_broker)
    origin = _build_source(
        source, manifest=manifest, directory=directory, settings=settings, runner=runner
    )
    stubs = _cli_call(origin.search(query, limit=limit), action=f"search in {source!r}")
    if not stubs:
        ui.warning(f"No skills matching {query!r} in {source!r}.")
        return
    ui.section(f"{len(stubs)} hit(s) in {source}")
    for stub in stubs:
        ui.bullet(f"{stub.name} [{stub.source}]", stub.description or stub.origin)


@app.command("find")
def find_skills(
    query: str,
    crawl: Annotated[
        bool, typer.Option("--crawl", help="Also search remote catalogs (hits the network).")
    ] = False,
    directory: DirOption = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max hits.")] = 5,
    config: ConfigOption = None,
) -> None:
    """Find skills for a task: installed first, remote catalogs with --crawl."""
    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    sources: list[Any] = []
    if crawl:
        sources.append(_build_crawl_source(settings, skills_dir))
    resolver = SkillResolver(
        index=SkillIndex(index_path(skills_dir)),
        sources=sources,
        skills_dir=skills_dir,
    )
    resolution = _cli_call(
        resolver.resolve(query, crawl=crawl, limit=limit), action=f"find {query!r}"
    )
    typer.echo(resolution.to_text())


@app.command("crawl")
def crawl_skills(
    directory: DirOption = None,
    config: ConfigOption = None,
) -> None:
    """Refresh the remote candidate cache from the configured catalog sites."""

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    sites = settings.skills.catalog_sites
    source = _build_crawl_source(settings, skills_dir)
    where = (
        f"{len(sites)} configured site(s)"
        if sites
        else "the public skill ecosystem (GitHub marketplace manifests)"
    )
    ui.section(f"Discovering skills from {where}")
    # ``full=True`` stores every discovered skill, not a query-sized slice: a
    # refresh should populate the cache completely, since each subsequent
    # ``skill_search`` reads it without touching the network.
    count = _cli_call(source.refresh(full=True), action="discover skills")
    ui.success(f"Cached {count} candidate(s) -> {source.path if hasattr(source,'path') else ''}")


@app.command("index")
def index_skills(
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Re-scan the skills directory.")
    ] = False,
    directory: DirOption = None,
    config: ConfigOption = None,
) -> None:
    """Show or rebuild the local skill index snapshot.

    A rebuild reconciles the snapshot against the registry and reports the
    divergence instead of rewriting it silently. Without a registry (``--dir``
    on a standalone tree) it is a plain disk scan, and says so.
    """
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    index = SkillIndex(index_path(skills_dir))
    if rebuild:
        if directory:
            records = index.rebuild(skills_dir)
            ui.success(f"Indexed {len(records)} skill(s) from disk -> {index.path}")
            return
        storage = create_storage(settings.storage, memory_settings=settings.memory)
        if storage.skills is None:
            records = index.rebuild(skills_dir)
            ui.success(f"Indexed {len(records)} skill(s) from disk -> {index.path}")
            return
        report, records = reconcile(storage.skills, skills_dir)
        ui.success(f"Indexed {len(records)} skill(s) -> {index.path}")
        for record in report.missing:
            ui.error(
                f"{record.name} is registered but its files are gone "
                f"({record.path or 'no path recorded'}) — left in the registry, "
                f"dropped from the snapshot"
            )
        for record in report.unregistered:
            ui.warning(
                f"{record.name} is on disk but not registered — it loads untrusted "
                "and stays out of the prompt"
            )
        return
    records = index.list()
    if not records:
        ui.warning("The index is empty. Run `sprout skills index --rebuild`.")
        return
    ui.section(f"Indexed skills ({len(records)})")
    for record in records:
        ui.bullet(f"{record.name} [{record.trust}]", record.description or record.source)


@app.command("forget")
def forget_skill(
    name: str,
    directory: DirOption = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Drop a skill's registry row without touching its files.

    The counterpart to a MISSING entry in `sprout skills list`: a row whose
    install is gone stays in the registry on purpose, so an operator can see it,
    and this is how it is cleared. To remove the files as well, delete them from
    the skills directory and run `sprout skills index --rebuild`.
    """
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    if directory:
        ui.error("--dir has no registry to forget from; it is a standalone tree.")
        raise typer.Exit(code=2)

    storage = create_storage(settings.storage, memory_settings=settings.memory)
    if storage.skills is None:
        ui.error("No skill registry is configured.")
        raise typer.Exit(code=2)
    record = asyncio.run(storage.skills.get(name))
    if record is None:
        ui.error(f"No skill named {name!r} in the registry.")
        raise typer.Exit(code=1)

    present = _artifact_present(record)
    where = record.path or "(no path recorded)"
    ui.warning(
        f"{name} is {'still present at' if present else 'missing from'} {where}"
    )
    if present and not yes:
        ui.warning("Its files will be left on disk and re-indexed as unregistered.")
    if not yes and not typer.confirm(f"Forget {name}?", default=False):
        ui.warning("Left unchanged.")
        return

    asyncio.run(storage.skills.remove(name))
    reconcile(storage.skills, skills_dir)
    ui.success(f"Forgot {name}.")


@app.command("install")
def install_skill(
    name: str,
    source: Annotated[
        str, typer.Option("--source", "-s", help="Source to install from.")
    ] = "catalog",
    manifest: ManifestOption = None,
    origin: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="Directory to look <name> up in. Required for --source local/project.",
        ),
    ] = None,
    directory: DirOption = None,
    via_broker: Annotated[
        bool, typer.Option("--via-broker", help="Route git/curl through the policy broker.")
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Install a skill through the policy engine and approval flow.

    ``--dir`` is the *destination* skills directory; ``--from`` is the directory
    the skill is read from. They used to be the same option, so
    ``install a --source local --dir X`` copied ``X/a`` to ``X/a-<digest>`` —
    a duplicate of itself, in place.
    """
    from Sprout.security.layer import SecurityLayer
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    if source in _LOCAL_SOURCES and not origin and not manifest:
        # Without a source directory the old behaviour silently searched the
        # destination, which is how the in-place copy happened. Name the fix
        # instead of reproducing it.
        ui.error(
            f"--source {source} needs --from <dir>: --dir is the destination, "
            "not the place to look the skill up."
        )
        raise typer.Exit(code=2)
    storage = create_storage(settings.storage, memory_settings=settings.memory)
    layer = SecurityLayer.from_settings(settings.security, store=storage.operational)
    approvals = layer.approvals or ApprovalManager(
        storage.operational,
        policy=ApprovalPolicy.from_settings(settings.security),
        audit=layer.audit,
    )

    runner = _build_runner(settings, source=source, via_broker=via_broker, layer=layer)
    if source == "catalog":
        # The default path: resolve a *name* against the discovered cache, which
        # is what ``skills find`` reports and what a user then types here.
        source_origin = _installable_source(settings, skills_dir)
    else:
        source_origin = _build_source(
            source,
            manifest=manifest,
            directory=origin,
            settings=settings,
            runner=runner,
        )
    candidates = _cli_call(source_origin.search(name, limit=25), action=f"search in {source!r}")
    # A skill *name* addresses exactly one stub; a *locator* (``url`` / ``github``)
    # resolves to the single skill it points at (design §12: ``install <src>``).
    exact = [stub for stub in candidates if stub.name == name]
    if exact:
        stub = exact[0]
    elif len(candidates) == 1:
        stub = candidates[0]
    else:
        ui.error(f"No skill named {name!r} in source {source!r}.")
        raise typer.Exit(code=1)

    broker = SkillInstallBroker(
        layer.policy_engine,
        approvals=approvals,
        skills=storage.skills,
    )
    # An install already approved for this exact scope skips the second round
    # trip: ``single_use`` grants are consumed by the policy engine, so the
    # broker's own evaluation is what decides whether one is still available.
    report = _cli_call(
        broker.install(stub, source_origin, skills_dir=skills_dir),
        action=f"install {stub.name!r}",
    )
    if report.installed:
        ui.success(f"Installed {stub.name} -> {report.installed_path}")
    elif report.pending_approval:
        approval_id = report.outcome.approval_id or "pending"
        ui.warning(f"{stub.name} needs approval (id={approval_id[:8]})")
        # Ask now: the skill is already staged, so approving here completes the
        # install instead of leaving it parked in quarantine forever.
        if typer.confirm(f"Install {stub.name} from {stub.origin}?", default=False):
            _cli_call(
                approvals.decide(
                    approval_id, True, decided_by="cli", channel="cli"
                ),
                action=f"approve {stub.name!r}",
            )
            promoted = _cli_call(
                broker.promote_approved(
                    stub.name,
                    source=stub.source,
                    origin=stub.origin,
                    digest=report.digest,
                    skills_dir=skills_dir,
                ),
                action=f"promote {stub.name!r}",
            )
            if promoted.installed:
                ui.success(f"Installed {stub.name} -> {promoted.installed_path}")
            else:
                ui.error(f"Could not promote {stub.name}: {promoted.outcome.reason}")
                raise typer.Exit(code=1)
        else:
            ui.warning(
                f"Left {stub.name} in quarantine; approve later with "
                f"`sprout approvals approve {approval_id[:8]}`"
            )
    else:
        ui.error(f"Rejected {stub.name}: {report.outcome.reason}")
        raise typer.Exit(code=1)


@app.command("import")
def import_skills(
    path: str,
    directory: DirOption = None,
    depth: Annotated[
        int, typer.Option("--max-depth", help="How deep to search for skills.")
    ] = 8,
    force: Annotated[
        bool, typer.Option("--force", help="Replace a skill of the same name.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be imported; write nothing.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    config: ConfigOption = None,
) -> None:
    """Import every skill under a local directory into the skills directory.

    Walks PATH recursively: a directory holding a SKILL.md is one skill and is
    not searched further inside, and single-file *.toml skills are collected
    along the way. Each one goes through the ordinary broker — scanned, then
    decided by the policy engine. A local path is a first-party source, so
    nothing needs approving; the scanner's fatal-finding floor still applies and
    cannot be approved past.

    Examples:
        sprout skills import ~/code/my-skills
        sprout skills import D:/skills --dry-run
    """
    import json

    from Sprout.security.layer import SecurityLayer
    from Sprout.skills.sources.tree import scan_tree
    from Sprout.storage.bundle import create_storage

    settings = load_settings(config)
    skills_dir = _skills_dir(directory, settings)
    source_root = Path(path).expanduser()
    if not source_root.is_dir():
        ui.error(f"Not a directory: {source_root}")
        raise typer.Exit(code=2)

    # Never walk into the destination: `import .` with the default skills dir
    # would rediscover everything the run just wrote.
    found, warnings = scan_tree(source_root, max_depth=depth, exclude=[skills_dir])
    for warning in warnings:
        ui.warning(f"Skipped {warning.path}: {warning.reason}")
    if not found:
        ui.warning(f"No skills found under {source_root}.")
        raise typer.Exit(code=1)

    if dry_run:
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "path": str(source_root),
                        "skills_dir": str(skills_dir),
                        "skills": [
                            {
                                "name": item.name,
                                "artifact": str(item.artifact),
                                "description": item.skill.description,
                            }
                            for item in found
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        ui.section(f"Would import {len(found)} skill(s) into {skills_dir}")
        for item in found:
            ui.bullet(item.name, str(item.artifact))
        return

    storage = create_storage(settings.storage, memory_settings=settings.memory)
    layer = SecurityLayer.from_settings(settings.security, store=storage.operational)
    # The skill registry is a global table keyed by name, while ``--dir`` picks a
    # tree on disk. Writing a custom tree's skills into the global registry would
    # make the next plain ``skills list`` report skills that are not under the
    # configured root, so a custom ``--dir`` stays JSON-index-only — the snapshot
    # is written from what actually landed, below.
    skills_store = None if directory else storage.skills
    broker = SkillInstallBroker(layer.policy_engine, skills=skills_store)
    existing = _installed_names(skills_store, skills_dir)

    # A ``LocalDirSource`` per skill root keeps the fetch contract unchanged: the
    # broker still calls ``source.fetch(stub)`` and still stages the result.
    installed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for item in found:
        if item.name in existing and not force:
            skipped.append({"name": item.name, "reason": "already installed"})
            continue
        origin = LocalDirSource(item.artifact, source="local")
        stub = _stub_for(item)
        report = _cli_call(
            broker.install(stub, origin, skills_dir=skills_dir, replace=force),
            action=f"import {item.name!r}",
        )
        if report.installed:
            installed.append({"name": item.name, "path": report.installed_path})
        elif report.rejected:
            rejected.append({"name": item.name, "reason": report.outcome.reason})
        else:
            rejected.append(
                {
                    "name": item.name,
                    "reason": report.outcome.reason or "needs approval",
                }
            )

    if skills_store is None and installed:
        # No registry to derive the snapshot from, so scan the tree we wrote and
        # index that. It is the same single scan path the loader uses.
        SkillIndex(index_path(skills_dir)).rebuild(skills_dir)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "path": str(source_root),
                    "skills_dir": str(skills_dir),
                    "installed": installed,
                    "skipped": skipped,
                    "rejected": rejected,
                    "warnings": [
                        {"path": str(warning.path), "reason": warning.reason}
                        for warning in warnings
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        ui.section(f"Imported {len(installed)} of {len(found)} skill(s) into {skills_dir}")
        for record in installed:
            ui.success(f"{record['name']} -> {record['path']}")
        for record in skipped:
            ui.warning(f"{record['name']}: {record['reason']} (use --force to replace)")
        for record in rejected:
            ui.error(f"{record['name']}: {record['reason']}")

    if rejected:
        raise typer.Exit(code=1)


def _installed_names(skills_store: Any, skills_dir: Path) -> set[str]:
    """Names already present, from the registry or the tree's own snapshot.

    With a registry (the normal case) it is the authority; when ``--dir`` points
    at a standalone tree there is no registry entry to consult, so the tree's
    ``index.json`` stands in — that is what the tree itself would load.
    """
    if skills_store is not None:
        return {record.name for record in asyncio.run(skills_store.list())}
    return {record.name for record in SkillIndex(index_path(skills_dir)).list()}


def _stub_for(item: Any) -> Any:
    """Build the :class:`SkillStub` for one scanned skill.

    The scan already parsed the skill, so this mirrors what ``LocalDirSource``
    would return for it — same origin, same digest — without a second disk walk.
    """
    from Sprout.skills.loader import artifact_digest
    from Sprout.skills.sources.base import SkillStub

    skill = item.skill
    return SkillStub(
        name=skill.name,
        source="local",
        origin=str(item.artifact),
        description=skill.description,
        version=skill.version,
        tags=skill.tags,
        digest=artifact_digest(item.artifact),
        install_command=skill.install_command,
        requires_cli=skill.requires_cli,
        cli_install_command=skill.cli_install_command,
    )

"""``sprout gateway``: set up and run long-lived external channel gateways."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui
from Sprout.config.loader import load_settings
from Sprout.config.settings import Settings
from Sprout.gateway.channels.feishu_client import FeishuClient
from Sprout.gateway.channels.feishu_ws import FeishuWebSocketGateway
from Sprout.gateway.channels.weixin_ilink import (
    WeixinIlinkAccount,
    WeixinIlinkAccountStore,
    WeixinIlinkClient,
    WeixinIlinkGateway,
    WeixinIlinkStateStore,
)

app = typer.Typer(help="Run external messaging channel gateways.", no_args_is_help=True)


def _resolve_weixin_paths(settings: Settings, accounts_dir: str | None) -> tuple[Path, Path]:
    accounts = Path(accounts_dir or settings.weixin_ilink.accounts_dir)
    context = Path(settings.weixin_ilink.context_tokens_dir)
    return accounts, context


def _qr_id(payload: dict) -> str:
    for key in ("qrcode", "qrcode_id", "qr_id", "code_id", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _qr_display(payload: dict) -> str:
    for key in (
        "qrcode_img_content",
        "qrcode_value",
        "qr_value",
        "qrcode_url",
        "qr_url",
        "url",
    ):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _status_line(payload: dict) -> str:
    state = payload.get("status") or payload.get("state") or "waiting"
    error = payload.get("errmsg") or payload.get("err_msg")
    if error:
        return f"{state}: {error}"
    return str(state)


@app.command("setup")
def setup(
    channel: Annotated[
        str | None,
        typer.Option("--channel", help="Channel to configure."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to sprout.toml."),
    ] = None,
    accounts_dir: Annotated[
        str | None,
        typer.Option("--accounts-dir", help="Override the account storage directory."),
    ] = None,
) -> None:
    """Set up a messaging channel, then optionally connect it right away."""
    if channel is None:
        raw = typer.prompt(
            "Channel [1=wechat-ilink, 2=feishu]",
            default="1",
        ).strip()
        if raw in {"1", "wechat-ilink", "wechat"}:
            channel = "wechat-ilink"
        elif raw in {"2", "feishu"}:
            channel = "feishu"
        else:
            ui.error(f"Unsupported channel: {raw}")
            raise typer.Exit(code=1)

    if channel not in {"wechat-ilink", "feishu"}:
        ui.error(f"Unsupported channel: {channel}")
        raise typer.Exit(code=1)

    settings = load_settings(config)
    if channel == "feishu":
        if not _setup_feishu(settings, config=config):
            return
    else:
        accounts_path, _ = _resolve_weixin_paths(settings, accounts_dir)
        client = WeixinIlinkClient(base_url=settings.weixin_ilink.base_url)
        if not asyncio.run(_setup_weixin_ilink(client, accounts_path)):
            return

    _ensure_default_workspace(settings, channel, config=config)

    if not typer.confirm("Connect the gateway now?", default=True):
        return
    if channel == "feishu":
        _run_feishu(settings)
    else:
        _run_wechat_gateway(settings, accounts_dir)


def _setup_feishu(settings: Settings, *, config: str | None = None, force: bool = False) -> bool:
    typer.echo(ui.text("Feishu Gateway Setup", bold=True))
    mode = typer.prompt(
        "Mode [1=scan to create a new app (recommended), 2=enter an existing app]",
        default="1",
    ).strip()
    if mode in {"2", "manual", "existing"}:
        return _setup_feishu_manual(settings, config=config, force=force)
    return asyncio.run(_setup_feishu_qr(settings, config=config))


def _setup_feishu_manual(
    settings: Settings,
    *,
    config: str | None = None,
    force: bool = False,
) -> bool:
    if not _ensure_feishu_env(settings, "app_id_env", "Feishu App ID", force=force):
        return False
    if not _ensure_feishu_env(
        settings,
        "app_secret_env",
        "Feishu App Secret",
        secret=True,
        force=force,
    ):
        return False
    # The verification token is what proves a callback came from Feishu. It used
    # to be shown here but never collected, so the guided setup produced a
    # deployment that accepted forged events.
    if not _ensure_feishu_env(
        settings,
        "verification_token_env",
        "Feishu Verification Token (Event Subscriptions > Verification Token)",
        secret=True,
        force=force,
    ):
        return False
    _save_feishu_credentials(settings, config)
    fields = {
        "mode": "websocket (long connection)",
        "domain": settings.feishu.domain,
        "verification_token_env": settings.feishu.verification_token_env,
        "app_id_env": settings.feishu.app_id_env,
        "app_secret_env": settings.feishu.app_secret_env,
        "encrypt_key_env": settings.feishu.encrypt_key_env,
        "default_workspace_id": settings.feishu.default_workspace_id,
    }
    for key, value in fields.items():
        if key.endswith("_env"):
            status = "set" if os.getenv(value, "") else "missing"
            typer.echo(ui.key_value(key, f"{value} ({status})"))
        else:
            typer.echo(ui.key_value(key, value))
    return True


async def _setup_feishu_qr(settings: Settings, *, config: str | None = None) -> bool:
    """Create a new Feishu/Lark app by scan-to-create and persist its credentials."""
    from lark_oapi.scene.registration import (
        AppAccessDeniedError,
        AppExpiredError,
        RegisterAppError,
        aregister_app,
    )

    typer.echo(ui.muted("Requesting a Feishu/Lark authorization link..."))
    cancel_task = asyncio.create_task(_prompt_enter_to_cancel())

    def on_qr(info: dict) -> None:
        url = info.get("url", "")
        typer.echo("")
        typer.echo(ui.text("Open this link in Feishu/Lark to authorize:", bold=True))
        typer.echo(ui.value(url))
        typer.echo(ui.muted(f"Link expires in {info.get('expire_in', 0)} seconds."))

    def on_status(info: dict) -> None:
        if info.get("status") == "domain_switched":
            typer.echo(ui.muted("Lark tenant detected; switching to the international domain."))

    async def register() -> dict:
        return await aregister_app(
            on_qr_code=on_qr,
            on_status_change=on_status,
            source="sema",
            app_preset={"name": "SEMA"},
        )

    reg_task = asyncio.create_task(register())
    try:
        done, _ = await asyncio.wait(
            {reg_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done:
            reg_task.cancel()
            typer.echo(ui.muted("Scan-to-create cancelled."))
            return False
        result = reg_task.result()
    except AppExpiredError:
        ui.error("Authorization timed out before the link was used.")
        return False
    except AppAccessDeniedError:
        ui.error("Authorization was denied.")
        return False
    except RegisterAppError as exc:
        ui.error(f"Scan-to-create failed: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - clean feedback for network/parse failures
        ui.error(f"Scan-to-create failed: {exc}")
        return False
    finally:
        cancel_task.cancel()

    app_id = str(result.get("client_id") or "")
    app_secret = str(result.get("client_secret") or "")
    if not app_id or not app_secret:
        ui.error("Feishu did not return app credentials.")
        return False

    user_info = result.get("user_info") or {}
    if user_info.get("tenant_brand") == "lark":
        settings.feishu.domain = "lark"

    settings.feishu.enabled = True
    settings.feishu.app_id = app_id
    settings.feishu.app_secret = app_secret
    os.environ[settings.feishu.app_id_env] = app_id
    os.environ[settings.feishu.app_secret_env] = app_secret
    _save_feishu_credentials(settings, config)
    ui.success("Created and saved the Feishu app credentials.")
    typer.echo(ui.key_value("app_id", app_id))
    typer.echo(ui.key_value("domain", settings.feishu.domain))
    return True


async def _open_cwd_workspace(settings: Settings) -> str:
    """Register the current directory as a workspace without requiring a model."""
    from Sprout.runtime.workspaces import WorkspaceService
    from Sprout.storage.bundle import create_storage
    from Sprout.storage.local.sqlite.driver import SqlitePragmas

    sqlite_cfg = settings.sqlite
    pragmas = SqlitePragmas(
        busy_timeout_ms=sqlite_cfg.busy_timeout_ms,
        synchronous=sqlite_cfg.synchronous,
        wal_autocheckpoint=sqlite_cfg.wal_autocheckpoint,
        mmap_size=sqlite_cfg.mmap_size,
        readers=sqlite_cfg.readers,
    )
    storage = create_storage(
        settings.storage,
        pragmas=pragmas,
        memory_settings=settings.memory,
    )
    workspace = await WorkspaceService(storage).open(Path.cwd())
    return workspace.id


def _persist_default_workspace(section: str, workspace_id: str, config: str | None) -> None:
    """Write ``default_workspace_id`` inside ``[section]`` without touching the rest."""
    path = Path(config) if config else Path.home() / ".sprout" / "sprout.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    marker = "default_workspace_id"
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)
    if start is None:
        lines.extend(["", f"[{section}]", f'{marker} = "{workspace_id}"'])
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("["):
                end = i
                break
        for i in range(start + 1, end):
            if lines[i].strip().startswith(marker):
                lines[i] = f'{marker} = "{workspace_id}"'
                break
        else:
            lines.insert(start + 1, f'{marker} = "{workspace_id}"')
    path.write_text("\n".join(lines), encoding="utf-8")


def _ensure_default_workspace(
    settings: Settings,
    channel: str,
    *,
    config: str | None = None,
) -> None:
    """Auto-register cwd as the default workspace when the channel has none."""
    current = (
        settings.feishu.default_workspace_id
        if channel == "feishu"
        else settings.weixin_ilink.default_workspace_id
    )
    if current:
        typer.echo(ui.muted(f"Using default workspace {current}"))
        return

    typer.echo(ui.muted("No default workspace configured; registering the current directory..."))
    try:
        workspace_id = asyncio.run(_open_cwd_workspace(settings))
    except Exception as exc:  # noqa: BLE001 - never block setup on workspace auto-open
        ui.warning(f"Could not register a default workspace automatically: {exc}")
        return

    section = "feishu" if channel == "feishu" else "weixin_ilink"
    if channel == "feishu":
        settings.feishu.default_workspace_id = workspace_id
    else:
        settings.weixin_ilink.default_workspace_id = workspace_id
    _persist_default_workspace(section, workspace_id, config)
    typer.echo(ui.key_value("default workspace", workspace_id))


def _save_feishu_credentials(settings: Settings, config: str | None) -> None:
    """Persist collected Feishu credentials to ``~/.sprout/sprout.toml``."""
    path = Path(config) if config else Path.home() / ".sprout" / "sprout.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    start = next((i for i, line in enumerate(lines) if line.strip() == "[feishu]"), None)
    end = None
    if start is not None:
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("["):
                end = i
                break
        lines = lines[:start] + lines[end or len(lines) :]
    block = [
        "[feishu]",
        f'enabled = {"true" if settings.feishu.enabled else "false"}',
        f'domain = "{settings.feishu.domain}"',
        f'default_workspace_id = "{settings.feishu.default_workspace_id}"',
    ]
    for env_field, value_field in (
        ("app_id_env", "app_id"),
        ("app_secret_env", "app_secret"),
        ("verification_token_env", "verification_token"),
        ("encrypt_key_env", "encrypt_key"),
    ):
        env_name = getattr(settings.feishu, env_field)
        value = getattr(settings.feishu, value_field) or os.getenv(env_name, "")
        block.append(f'{env_field} = "{env_name}"')
        if value:
            block.append(f'{value_field} = "{value}"')
    block.append("")
    path.write_text("\n".join([*lines, *block]), encoding="utf-8")
    typer.echo(ui.muted(f"Saved Feishu credentials to {path}"))


def _ensure_feishu_env(
    settings: Settings,
    field: str,
    label: str,
    *,
    secret: bool = False,
    force: bool = False,
) -> bool:
    """Prompt for a Feishu credential when it is not already in the environment."""
    env_name = getattr(settings.feishu, field)
    value_field = {
        "app_id_env": "app_id",
        "app_secret_env": "app_secret",
        "verification_token_env": "verification_token",
        "encrypt_key_env": "encrypt_key",
    }[field]
    configured = getattr(settings.feishu, value_field) or os.getenv(env_name, "")
    if configured and not force:
        return True
    value = typer.prompt(label, hide_input=secret)
    if value.strip():
        os.environ[env_name] = value.strip()
        setattr(settings.feishu, value_field, value.strip())
        return True
    typer.echo(ui.muted("Gateway setup cancelled: no value provided."))
    return False


def _show_feishu_existing(settings: Settings) -> None:
    """Show the currently configured Feishu environment."""
    typer.echo(ui.text("Feishu Existing Configuration", bold=True))
    for env_field, value_field, label in (
        ("app_id_env", "app_id", "App ID"),
        ("app_secret_env", "app_secret", "App Secret"),
        ("verification_token_env", "verification_token", "Verification Token"),
        ("encrypt_key_env", "encrypt_key", "Encrypt Key"),
    ):
        env_name = getattr(settings.feishu, env_field)
        configured = getattr(settings.feishu, value_field) or os.getenv(env_name, "")
        status = "set" if configured else "missing"
        typer.echo(ui.key_value(label, f"{env_name} ({status})"))
    typer.echo(
        ui.key_value(
            "default workspace",
            settings.feishu.default_workspace_id or "(not set)",
        )
    )


async def _probe_feishu_token(client: FeishuClient) -> None:
    await client.get_tenant_access_token()


async def _setup_weixin_ilink(client: WeixinIlinkClient, accounts_path: Path) -> bool:
    typer.echo(ui.text("Weixin iLink QR login", bold=True))
    qr = await client.request_qr()
    qr_id = _qr_id(qr)
    display = _qr_display(qr)
    if not display:
        ui.error("iLink did not return a QR code payload.")
        typer.echo(qr)
        raise typer.Exit(code=1)

    typer.echo(ui.key_value("scan", display))
    if not qr_id:
        ui.error("iLink QR response is missing qrcode_id.")
        typer.echo(qr)
        raise typer.Exit(code=1)

    cancel_task = asyncio.create_task(_prompt_enter_to_cancel())
    try:
        for attempt in range(1, 61):
            poll_task = asyncio.create_task(client.poll_qr_status(qr_id))
            done, _ = await asyncio.wait(
                {poll_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                poll_task.cancel()
                typer.echo(ui.muted("QR login cancelled."))
                return False
            status = poll_task.result()
            try:
                account = WeixinIlinkAccount.from_payload(status)
            except ValueError:
                typer.echo(ui.muted(f"waiting ({attempt}/60): {_status_line(status)}"))
                sleep_task = asyncio.create_task(asyncio.sleep(2.0))
                done, _ = await asyncio.wait(
                    {sleep_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done:
                    typer.echo(ui.muted("QR login cancelled."))
                    return False
                sleep_task.cancel()
                continue

            path = WeixinIlinkAccountStore(accounts_path).save(account)
            typer.echo(ui.muted("login complete"))
            typer.echo(ui.key_value("account id", account.account_id or "(missing)"))
            typer.echo(ui.key_value("saved", str(path)))
            return True
    finally:
        cancel_task.cancel()

    ui.error("QR login timed out.")
    return False


async def _prompt_enter_to_cancel() -> bool:
    """Wait for the user to press Enter and cancel the pending operation."""
    from prompt_toolkit import PromptSession

    session = PromptSession()
    try:
        await session.prompt_async("Press Enter to cancel... ")
    except (EOFError, KeyboardInterrupt):
        return False
    return True


@app.command("run")
def run(
    channel: Annotated[
        str,
        typer.Option("--channel", help="Channel to run."),
    ] = "wechat-ilink",
    config: Annotated[
        str | None,
        typer.Option("--config", help="Path to sprout.toml."),
    ] = None,
    accounts_dir: Annotated[
        str | None,
        typer.Option("--accounts-dir", help="Override the account storage directory."),
    ] = None,
) -> None:
    """Run a configured external gateway until interrupted."""
    if channel not in {"wechat-ilink", "feishu"}:
        ui.error(f"Unsupported channel: {channel}")
        raise typer.Exit(code=1)

    settings = load_settings(config)
    if channel == "feishu":
        _run_feishu(settings)
    else:
        _run_wechat_gateway(settings, accounts_dir)


def _run_wechat_gateway(settings: Settings, accounts_dir: str | None) -> None:
    """Load a saved iLink account and run the Weixin gateway until interrupted."""
    accounts_path, context_path = _resolve_weixin_paths(settings, accounts_dir)
    account = WeixinIlinkAccountStore(accounts_path).load()
    if account is None:
        ui.error("No saved iLink account. Run `sprout gateway setup` first.")
        raise typer.Exit(code=1)

    from Sprout.runtime.factory import create_runtime

    runtime = create_runtime(settings)
    asyncio.run(_run_weixin_ilink(runtime, settings, account, context_path))


def _run_feishu(settings: Settings) -> None:
    log_level = os.getenv("FEISHU_LOG_LEVEL", "info").lower()
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The SDK configures its own "Lark" handler; avoid double-printing.
    logging.getLogger("Lark").propagate = False
    app_id = os.getenv(settings.feishu.app_id_env, "")
    app_secret = os.getenv(settings.feishu.app_secret_env, "")
    if not app_id or not app_secret:
        ui.error(
            "Feishu credentials missing; set "
            f"{settings.feishu.app_id_env} and {settings.feishu.app_secret_env}."
        )
        raise typer.Exit(code=1)

    from Sprout.runtime.factory import create_runtime

    runtime = create_runtime(settings)
    base_url = (
        "https://open.feishu.cn"
        if settings.feishu.domain == "feishu"
        else "https://open.larksuite.com"
    )
    client = FeishuClient(app_id=app_id, app_secret=app_secret, base_url=base_url)
    try:
        asyncio.run(_probe_feishu_token(client))
    except Exception as exc:  # noqa: BLE001 - clean credential feedback
        ui.error(f"Feishu credential check failed: {exc}")
        raise typer.Exit(code=1) from None

    gateway = FeishuWebSocketGateway(
        runtime,
        app_id=app_id,
        app_secret=app_secret,
        verification_token=os.getenv(settings.feishu.verification_token_env, ""),
        encrypt_key=os.getenv(settings.feishu.encrypt_key_env, ""),
        default_workspace_id=settings.feishu.default_workspace_id,
        domain=settings.feishu.domain,
        log_level=log_level,
        reply_client=client,
    )

    gateway.submit(runtime.start()).result(timeout=30)
    mcp_manager = None
    if settings.mcp.clients:
        from Sprout.mcp.client import attach_mcp_clients

        mcp_manager = gateway.submit(attach_mcp_clients(runtime, settings)).result(
            timeout=30
        )
    if settings.evolution.enabled:
        from Sprout.evolution import attach_evolution

        attach_evolution(runtime, settings)

    typer.echo(ui.banner("SEMA Feishu Gateway", subtitle="websocket long connection"))
    typer.echo(ui.muted("Press Ctrl+C to stop."))
    try:
        gateway.start()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001 - clean connection feedback
        ui.error(f"Feishu gateway stopped: {exc}")
    finally:
        if mcp_manager is not None:
            gateway.submit(mcp_manager.stop()).result(timeout=15)
        gateway.submit(runtime.stop()).result(timeout=15)
        gateway.stop()


async def _run_weixin_ilink(
    runtime,
    settings: Settings,
    account: WeixinIlinkAccount,
    context_path: Path,
) -> None:
    from Sprout.runtime.lifecycle import managed

    client = WeixinIlinkClient(
        token=account.token,
        base_url=account.base_url,
    )
    account_id = account.account_id or "account"
    state_store = WeixinIlinkStateStore(
        context_path.parent / "state" / f"{account_id}.json",
        legacy_context_path=context_path / f"{account_id}.json",
    )
    gateway = WeixinIlinkGateway(
        runtime,
        client=client,
        account=account,
        default_workspace_id=settings.weixin_ilink.default_workspace_id,
        dm_policy=settings.weixin_ilink.dm_policy,
        allowed_users=settings.weixin_ilink.allowed_users,
        state_store=state_store,
    )

    mcp_manager = None
    if settings.mcp.clients:
        from Sprout.mcp.client import attach_mcp_clients

        mcp_manager = await attach_mcp_clients(runtime, settings)
    if settings.evolution.enabled:
        from Sprout.evolution import attach_evolution

        attach_evolution(runtime, settings)

    typer.echo(ui.banner("SEMA Weixin iLink Gateway", subtitle=account.account_id or "running"))
    typer.echo(ui.muted("Press Ctrl+C to stop."))
    try:
        async with managed(runtime):
            await gateway.run_forever()
    finally:
        if mcp_manager is not None:
            await mcp_manager.stop()

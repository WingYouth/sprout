"""``sprout model``: inspect and switch the active model configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from Sprout.cli import ui

app = typer.Typer(help="Inspect and switch model configuration.", no_args_is_help=True)


def model_configuration_issues(settings) -> list[str]:
    """Return safe, actionable reasons the interactive model is not configured."""
    model = settings.model
    issues: list[str] = []
    if model.provider not in {"aiyallm", "openai_compatible"}:
        issues.append("provider 未配置为远程模型（当前不能使用 echo 作为交互模型）")
    if not model.model or model.model == "echo":
        issues.append("model 名称为空或仍是 echo")
    if model.provider == "openai_compatible":
        if not model.base_url:
            issues.append("base_url 未配置")
        if not model.api_key_env:
            issues.append("api_key_env 未配置")
    return issues


def _config_path(config: str | None) -> Path:
    if config:
        return Path(config)
    local = Path("sprout.toml")
    if local.exists():
        return local
    return Path.home() / ".sprout" / "sprout.toml"


@app.command("list")
def list_cmd(
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Show the active model configuration."""
    from Sprout.config.loader import load_settings

    model = load_settings(config).model
    ui.banner("Active Model", subtitle="Current model configuration")
    typer.echo(ui.key_value("provider", model.provider))
    typer.echo(ui.key_value("model", model.model))
    typer.echo(ui.key_value("base_url", model.base_url))
    typer.echo(ui.key_value("api_key", "configured" if model.api_key else "local provider lookup"))
    typer.echo(ui.key_value("api_key_env", model.api_key_env))
    typer.echo(ui.key_value("timeout", f"{model.timeout_seconds:.0f}s"))
    temperature = model.temperature if model.temperature is not None else "default"
    typer.echo(ui.key_value("temperature", temperature))


@app.command("set")
def set_cmd(
    provider: Annotated[
        str, typer.Option("--provider", help="Provider: aiyallm or openai_compatible.")
    ],
    model: Annotated[str, typer.Option("--model", help="Model name.")],
    base_url: Annotated[str, typer.Option("--base-url", help="Provider base URL.")],
    api_key_env: Annotated[
        str,
        typer.Option(
            "--api-key-env",
            help="Environment variable name (only for openai_compatible).",
        ),
    ] = "",
    config: Annotated[
        str | None, typer.Option("--config", help="Path to sprout.toml.")
    ] = None,
) -> None:
    """Write a new [model] section into sprout.toml."""
    path = _config_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_model_section(
        path,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    ui.success(f"Model configuration written to {path}")


def _write_model_section(
    path: Path,
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "[model]"), None)
    end = None
    if start is not None:
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("["):
                end = i
                break
        lines = lines[:start] + lines[end or len(lines) :]
    block = [
        "[model]",
        f'provider = "{provider}"',
        f'model = "{model}"',
        f'base_url = "{base_url}"',
        f'api_key_env = "{api_key_env}"',
        "",
    ]
    path.write_text("\n".join([*lines, *block]), encoding="utf-8")

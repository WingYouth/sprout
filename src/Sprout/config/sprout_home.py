"""User-level ``~/.sprout`` bootstrap.

Every CLI entry point calls :func:`ensure_sprout_home` so a fresh install gets
the same home layout as other agent CLIs: config, logs, local data, memory, and
skills.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from Sprout.cli.i18n import L as _L


def sprout_home() -> Path:
    return Path.home() / ".sprout"


def ensure_sprout_home() -> None:
    """Create ``~/.sprout`` and default files when they are missing.

    Announces itself only when it actually creates something. The narration is
    for a first run — "here is what I am setting up" — but it printed on every
    invocation, so an established home reported the same three steps forever.
    That is noise on its own, and it is worse through the TUI: a ``/skill``
    slash command shells out to ``python -m Sprout.cli.app skills list``, and
    each fresh interpreter replayed the whole bootstrap above the answer.
    """
    home = sprout_home()
    fresh = not home.exists()

    def _say(index: int, zh: str, en: str) -> None:
        if fresh:
            print(_L(f"[{index}/3] {zh}", f"[{index}/3] {en}"))

    _say(1, "初始化 ~/.sprout 目录布局", "Ensuring ~/.sprout directory layout...")
    for directory in (
        home / "data",
        home / "data" / "audit",
        home / "data" / "context",
        home / "data" / "memory",
        home / "data" / "sprout_blobs",
        home / "data" / "sprout_trajectory",
        home / "data" / "projects",
        home / "skills",
        home / "docker",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _write_docker_files(home)

    _say(2, "写入缺失的配置文件", "Writing missing config files...")
    config_path = home / "sprout.toml"
    if not config_path.exists():
        config_path.write_text(_default_toml(home), encoding="utf-8")
    else:
        _migrate_storage_toml(config_path, home)

    _write_if_missing(
        home / "settings.json",
        {
            "theme": "dark",
            "language": "zh",
            "locale": "zh-CN",
            "telemetry": False,
            "tui": {"compact": True, "slash_menu": True},
        },
    )
    _write_if_missing(home / "mcp.json", {"servers": {}})
    _write_if_missing(
        home / "README.md",
        "# SEAM Sprout Home\n\n"
        "This directory is created automatically and owns local user state.\n",
    )

    _say(3, "预留本地数据库", "Reserving local databases...")
    # Reserve the default SQLite databases under the user home.
    from Sprout.config.loader import load_settings
    from Sprout.storage.bundle import create_storage

    try:
        settings = load_settings(config_path)
        bundle = create_storage(settings.storage, memory_settings=settings.memory)
        asyncio.run(bundle.close())
    except Exception:  # noqa: BLE001 - home bootstrap must not block CLI help
        print(
            _L(
                "本地数据库预留已跳过（本地文件可能只读）",
                "Sprout home database reservation skipped (local files may be read-only).",
            )
        )
    if fresh:
        print(_L("Sprout 主目录已就绪", "Sprout home ready."))


def _default_toml(home: Path) -> str:
    data = home / "data"
    return f"""\
# SEAM Sprout user configuration.
# Secrets stay in environment variables.

skills_dir = "{(home / 'skills').as_posix()}"

[[models]]
name = "deepseek"
account = "billing-deepseek"
type = "openai_compatible"
base_url = "https://api.deepseek.com"
models = ["deepseek-flash"]

[storage]
core = "sqlite:///{(data / 'sprout_core.db').as_posix()}"
conversation = "sqlite:///{(data / 'sprout_conversation.db').as_posix()}"
knowledge = "sqlite:///{(data / 'sprout_knowledge.db').as_posix()}"
audit = "sqlite:///{(data / 'sprout_audit.db').as_posix()}"
usage = "sqlite:///{(data / 'sprout_usage.db').as_posix()}"
context = "jsonl://{(data / 'context').as_posix()}"
blobs_dir = "{(data / 'sprout_blobs').as_posix()}"
trajectory_dir = "{(data / 'sprout_trajectory').as_posix()}"
project_root = "{(data / 'projects').as_posix()}"

[storage.observations]
enabled = true
dsn = "sqlite:///{(data / 'sprout_audit.db').as_posix()}"

[memory]
home = "{(data / 'memory').as_posix()}"

[web]
host = "127.0.0.1"
port = 8000
"""


def _write_if_missing(path: Path, payload: dict) -> None:
    if path.exists():
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _migrate_storage_toml(path: Path, home: Path) -> None:
    """Update an existing ``sprout.toml`` storage block to the two-layer layout.

    We deliberately edit only the storage-related lines so model credentials,
    gateway settings, and web/evolution options are preserved.
    """
    data = home / "data"
    values = {
        "core": f"sqlite:///{(data / 'sprout_core.db').as_posix()}",
        "conversation": f"sqlite:///{(data / 'sprout_conversation.db').as_posix()}",
        "knowledge": f"sqlite:///{(data / 'sprout_knowledge.db').as_posix()}",
        "audit": f"sqlite:///{(data / 'sprout_audit.db').as_posix()}",
        "usage": f"sqlite:///{(data / 'sprout_usage.db').as_posix()}",
        "context": f"jsonl://{(data / 'context').as_posix()}",
        "blobs_dir": f"{(data / 'sprout_blobs').as_posix()}",
        "trajectory_dir": f"{(data / 'sprout_trajectory').as_posix()}",
        "project_root": f"{(data / 'projects').as_posix()}",
    }
    legacy_removals = {"operational", "metadata", "session"}

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    section = ""
    seen_storage_keys: set[str] = set()
    migrated: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.strip("[]").strip()
            migrated.append(line)
            continue

        if section == "storage.observations" and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key == "dsn":
                migrated.append(f'dsn = "{values["audit"]}"')
                continue

        if section == "storage" and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in legacy_removals:
                continue
            if key in values:
                seen_storage_keys.add(key)
                migrated.append(f'{key} = "{values[key]}"')
                continue

        migrated.append(line)

    # Add missing public keys at the end of [storage] (before the next section).
    missing = [key for key in values if key not in seen_storage_keys]
    if missing:
        inserted: list[str] = []
        insert_after = None
        for index, line in enumerate(migrated):
            if line.strip() == "[storage]":
                insert_after = index
                break
        if insert_after is None:
            migrated.append("[storage]")
            insert_after = len(migrated) - 1
        for key in missing:
            inserted.append(f'{key} = "{values[key]}"')
        migrated[insert_after + 1 : insert_after + 1] = inserted

    updated = "\n".join(migrated) + ("\n" if original.endswith("\n") else "")
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def _write_docker_files(home: Path) -> None:
    """Copy the canonical Docker stack templates into ``~/.sprout/docker``."""
    docker_dir = home / "docker"
    template_dir = Path(__file__).resolve().parent / "docker_templates"
    if not template_dir.is_dir():
        return
    try:
        shutil.copytree(
            template_dir,
            docker_dir,
            dirs_exist_ok=True,
        )
    except Exception:  # noqa: BLE001 - bootstrap must not block the CLI entry point
        print(
            _L(
                "Docker 模板写入已跳过（本地文件可能只读）",
                "Docker template copy skipped (local files may be read-only).",
            )
        )

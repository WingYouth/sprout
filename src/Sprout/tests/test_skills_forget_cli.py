"""``sprout skills list`` / ``forget`` / ``index --rebuild`` on a diverged tree.

The production shape this pins: the registry held three skills, the tree held
one, and nothing said so — ``list`` read the store, ``index --rebuild`` read the
disk, and each looked self-consistent. These tests fix the behaviour that makes
the disagreement visible, and the command that resolves it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from Sprout.cli.app import app

runner = CliRunner()


def _skill(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    return folder


def _config(tmp_path: Path) -> tuple[Path, Path]:
    """Isolate both the registry and the skills tree inside ``tmp_path``.

    ``skills_dir`` is set in the config rather than passed as ``--dir``: ``--dir``
    is a standalone-tree escape hatch that bypasses the registry, and this file
    is precisely about the registry-versus-disk relationship.
    """
    skills_dir = tmp_path / "skills"
    path = tmp_path / "sprout.toml"
    audit = (tmp_path / "audit.db").as_posix()
    path.write_text(
        f'skills_dir = "{skills_dir.as_posix()}"\n'
        "\n[storage]\n"
        f'operational = "sqlite:///{audit}"\n'
        'session = "memory://"\n',
        encoding="utf-8",
    )
    return path, skills_dir


def _run(config: Path, *args: str):
    return runner.invoke(app, [*args, "--config", str(config)])


def _install(config: Path, skills_dir: Path, name: str):
    """Seed a skill through the real install path (source dir -> skills dir)."""
    incoming = skills_dir.parent / "incoming"
    _skill(incoming, name)
    return _run(
        config, "skills", "install", name, "--source", "local", "--from", str(incoming)
    )


def test_list_flags_a_registry_row_whose_files_are_gone(tmp_path: Path) -> None:
    config, skills_dir = _config(tmp_path)
    for name in ("present", "vanished"):
        assert _install(config, skills_dir, name).exit_code == 0
    shutil.rmtree(skills_dir / "vanished")

    listed = _run(config, "skills", "list")

    assert "present" in listed.output
    assert "[missing]" in listed.output
    assert "vanished" in listed.output
    assert "absent from disk" in listed.output


def test_rebuild_reports_the_divergence_instead_of_rewriting_silently(
    tmp_path: Path,
) -> None:
    config, skills_dir = _config(tmp_path)
    for name in ("present", "vanished"):
        assert _install(config, skills_dir, name).exit_code == 0
    shutil.rmtree(skills_dir / "vanished")

    result = _run(config, "skills", "index", "--rebuild")

    assert result.exit_code == 0, result.output
    assert "files are gone" in result.output
    assert "left in the registry" in result.output


def test_forget_drops_the_row_and_leaves_the_files(tmp_path: Path) -> None:
    config, skills_dir = _config(tmp_path)
    assert _install(config, skills_dir, "demo").exit_code == 0

    result = _run(config, "skills", "forget", "demo", "-y")

    assert result.exit_code == 0, result.output
    assert "Forgot demo" in result.output
    # files untouched — forgetting a row is not removing a skill
    assert (skills_dir / "demo" / "SKILL.md").is_file()
    assert "demo" not in _run(config, "skills", "list").output


def test_forget_warns_before_dropping_a_skill_that_is_still_present(
    tmp_path: Path,
) -> None:
    """It is a registry operation; say so rather than implying a delete."""
    config, skills_dir = _config(tmp_path)
    assert _install(config, skills_dir, "demo").exit_code == 0

    result = _run(config, "skills", "forget", "demo", "-y")

    assert "still present at" in result.output


def test_forget_an_unknown_name_is_reported(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)

    result = _run(config, "skills", "forget", "nope", "-y")

    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_forget_declines_without_confirmation(tmp_path: Path) -> None:
    config, skills_dir = _config(tmp_path)
    assert _install(config, skills_dir, "demo").exit_code == 0

    result = _run(config, "skills", "forget", "demo")  # no -y, no input

    assert "Forgot" not in result.output
    assert "demo" in _run(config, "skills", "list").output

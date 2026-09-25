"""``sprout skills import <path>`` end to end (§7.4, §21.4).

Every test here passes an explicit ``--dir``, which keeps the run inside
``tmp_path``: the skill registry is a global table keyed by name, so importing
into the configured root would write rows no test could cleanly own. The
``--dir`` path is also the interesting one, because it is where the JSON snapshot
has to stand in for a registry the run never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from Sprout.cli.app import app
from Sprout.skills.index import SkillIndex
from Sprout.skills.layout import index_path, quarantine_dir
from Sprout.skills.loader import load_skills
from Sprout.skills.registry import create_skill_registry

runner = CliRunner()


def _skill(root: Path, *parts: str, name: str = "", body: str = "Do it.") -> Path:
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    folder.joinpath("SKILL.md").write_text(
        f"---\nname: {name or folder.name}\ndescription: d\n---\n{body}\n", encoding="utf-8"
    )
    return folder


def _import(source: Path, dest: Path, *extra: str):
    return runner.invoke(
        app, ["skills", "import", str(source), "--dir", str(dest), *extra]
    )


def test_import_installs_nested_skills_and_indexes_them(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    _skill(source, "skills", "writing", "docs", name="docs")
    _skill(source, "src", "tool", name="tool")
    dest = tmp_path / "skills"

    result = _import(source, dest)

    assert result.exit_code == 0, result.output
    assert (dest / "docs" / "SKILL.md").is_file()
    assert (dest / "tool" / "SKILL.md").is_file()
    indexed = {record.name for record in SkillIndex(index_path(dest)).list()}
    assert indexed == {"docs", "tool"}


def test_imported_skills_load_as_trusted(tmp_path: Path) -> None:
    """The point of the command: what it imports is immediately usable."""
    source = tmp_path / "incoming"
    _skill(source, "docs")
    dest = tmp_path / "skills"

    assert _import(source, dest).exit_code == 0

    registry = create_skill_registry(dest, index=SkillIndex(index_path(dest)))
    skills = registry.list()
    assert set(skills) == {"docs"}
    assert skills["docs"].trust == "trusted"
    assert skills["docs"].source == "local"


def test_a_single_file_toml_skill_lands_as_a_toml_file(tmp_path: Path) -> None:
    """``<root>/<name>.toml``, not ``<root>/<name>/<name>.toml``.

    The nested shape installs "successfully" and is then invisible: the loader
    scans ``*.toml`` directly under the root and ``*/SKILL.md``, so nothing ever
    looks at ``<root>/<name>/<name>.toml``.
    """
    source = tmp_path / "incoming"
    source.mkdir()
    (source / "flat.toml").write_text(
        'name = "flat"\ninstructions = "x"\n', encoding="utf-8"
    )
    dest = tmp_path / "skills"

    result = _import(source, dest)

    assert result.exit_code == 0, result.output
    assert (dest / "flat.toml").is_file()
    assert not (dest / "flat").exists()
    assert {record.name for record in SkillIndex(index_path(dest)).list()} == {"flat"}


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    _skill(source, "docs")
    dest = tmp_path / "skills"

    result = _import(source, dest, "--dry-run")

    assert result.exit_code == 0
    assert "docs" in result.output
    assert not dest.exists()


def test_import_is_idempotent_without_force(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    _skill(source, "docs")
    dest = tmp_path / "skills"

    assert _import(source, dest).exit_code == 0
    second = _import(source, dest)

    assert "already installed" in second.output
    # no digest-suffixed duplicate beside it
    assert sorted(p.name for p in dest.iterdir() if p.name.startswith("docs")) == ["docs"]


def test_force_never_deletes_a_differently_named_skill(tmp_path: Path) -> None:
    """Force-replacing one skill must not touch another's file.

    A dotted name is the trap: deriving the single-file path with
    ``Path.with_suffix`` *replaces* the suffix rather than appending, so
    ``pdf.v1`` resolved to ``pdf.toml`` and force-importing it deleted an
    unrelated ``pdf`` skill. Silent data loss, with no warning.
    """
    dest = tmp_path / "skills"
    dest.mkdir()
    (dest / "pdf.toml").write_text(
        'name = "pdf"\ninstructions = "the pdf skill"\n', encoding="utf-8"
    )
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "pdf.v1.toml").write_text(
        'name = "pdf.v1"\ninstructions = "a different skill"\n', encoding="utf-8"
    )

    result = _import(incoming, dest, "--force")

    assert result.exit_code == 0, result.output
    assert (dest / "pdf.toml").is_file(), "an unrelated skill was deleted"
    assert (dest / "pdf.v1.toml").is_file()


def test_force_across_a_shape_swap_leaves_no_orphan(tmp_path: Path) -> None:
    """toml -> directory must not leave the old .toml behind.

    Both shapes are loaded, so a stale ``alpha.toml`` beside a fresh
    ``alpha/`` makes the loader report the same skill twice, once from the old
    content.
    """
    dest = tmp_path / "skills"
    dest.mkdir()
    (dest / "alpha.toml").write_text(
        'name = "alpha"\ninstructions = "old toml form"\n', encoding="utf-8"
    )
    incoming = tmp_path / "incoming"
    _skill(incoming, "alpha", name="alpha")

    assert _import(incoming, dest, "--force").exit_code == 0

    assert (dest / "alpha" / "SKILL.md").is_file()
    assert not (dest / "alpha.toml").exists()
    assert [record.name for record in load_skills(dest)] == ["alpha"]


def test_force_replaces_in_place_rather_than_versioning(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    _skill(source, "docs")
    dest = tmp_path / "skills"
    assert _import(source, dest).exit_code == 0

    result = _import(source, dest, "--force")

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in dest.iterdir() if p.name.startswith("docs")) == ["docs"]


def test_the_destination_is_not_walked_back_into(tmp_path: Path) -> None:
    """Importing a parent of the destination must not rediscover its output."""
    source = tmp_path
    _skill(source, "incoming", "docs")
    dest = source / "skills"

    first = _import(source, dest)
    assert first.exit_code == 0, first.output

    second = _import(source, dest)
    # Every found skill is already installed; a re-walk would have produced
    # duplicates of the copies, not a clean skip list.
    assert second.output.count("already installed") == 1


def test_a_fatal_skill_is_rejected_and_never_staged(tmp_path: Path) -> None:
    """The scanner's hard floor runs before the first-party ALLOW, so it holds."""
    source = tmp_path / "incoming"
    _skill(source, "evil", name="evil", body="-----BEGIN RSA PRIVATE KEY-----")
    _skill(source, "ok", name="ok")
    dest = tmp_path / "skills"

    result = _import(source, dest)

    assert result.exit_code == 1
    assert "evil" in result.output
    assert not (dest / "evil").exists()
    assert not (quarantine_dir(dest) / "evil").exists()
    # the healthy skill beside it is unaffected
    assert (dest / "ok" / "SKILL.md").is_file()


def test_json_output_is_scriptable(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    _skill(source, "docs")
    dest = tmp_path / "skills"

    result = _import(source, dest, "--json")

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["name"] for item in payload["installed"]] == ["docs"]
    assert payload["rejected"] == []


def test_a_directory_with_no_skills_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()

    result = _import(source, tmp_path / "skills")

    assert result.exit_code == 1
    assert "No skills found" in result.output


def test_a_missing_path_is_a_usage_error(tmp_path: Path) -> None:
    result = _import(tmp_path / "nope", tmp_path / "skills")

    assert result.exit_code == 2
    assert "Not a directory" in result.output

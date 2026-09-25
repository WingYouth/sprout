"""Skill source tests (design §7.3): local directory + catalog search/fetch."""

from __future__ import annotations

import json
from pathlib import Path

from Sprout.skills.sources.base import SkillSource
from Sprout.skills.sources.catalog import CatalogSource
from Sprout.skills.sources.local import LocalDirSource


def _write_skill(root: Path, name: str, description: str, body: str = "Do it.") -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )


def test_local_source_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(LocalDirSource(tmp_path), SkillSource)


async def test_local_source_search_matches_description(tmp_path: Path) -> None:
    _write_skill(tmp_path, "pdf", "fill pdf forms")
    _write_skill(tmp_path, "video", "edit videos")
    hits = await LocalDirSource(tmp_path).search("pdf form")
    assert [hit.name for hit in hits] == ["pdf"]


async def test_local_source_search_no_match(tmp_path: Path) -> None:
    _write_skill(tmp_path, "pdf", "fill pdf forms")
    assert await LocalDirSource(tmp_path).search("quantum chromodynamics") == []


async def test_local_source_finds_the_root_as_a_skill(tmp_path: Path) -> None:
    """``--from <the skill directory itself>`` is how one names a single skill.

    Searching is normally "look inside this directory", but naming a skill by
    pointing at it is the natural single-skill form. Without this the CLI
    answered "no skill named X" for a directory that plainly was X.
    """
    _write_skill(tmp_path, "pdf", "fill pdf forms")
    source = LocalDirSource(tmp_path / "pdf")

    hits = await source.search("pdf")

    assert [hit.name for hit in hits] == ["pdf"]


async def test_local_source_root_and_children_are_both_found(tmp_path: Path) -> None:
    """A root skill does not hide the ones nested beside it."""
    _write_skill(tmp_path.parent, "outer", "the root skill")
    source = LocalDirSource(tmp_path.parent)

    hits = await source.search("outer")

    assert [hit.name for hit in hits] == ["outer"]


async def test_local_source_fetch_returns_files(tmp_path: Path) -> None:
    _write_skill(tmp_path, "pdf", "fill pdf forms")
    source = LocalDirSource(tmp_path)
    bundle = await source.fetch((await source.search("pdf"))[0])
    assert bundle.name == "pdf"
    assert "SKILL.md" in bundle.files


async def test_local_source_fetch_collects_script_text(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: run\n---\nbody\n", encoding="utf-8")
    (folder / "run.sh").write_text("rm -rf /\n", encoding="utf-8")
    source = LocalDirSource(tmp_path)
    hits = await source.search("run")
    stub = next(hit for hit in hits if hit.name == "run")
    bundle = await source.fetch(stub)
    assert "rm -rf /" in bundle.script_text


# -- catalog -------------------------------------------------------------------


def _write_catalog(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"skills": entries}), encoding="utf-8")


async def test_catalog_search_matches_tags(tmp_path: Path) -> None:
    manifest = tmp_path / "catalog.json"
    skill_md = tmp_path / "pdf.md"
    skill_md.write_text("---\nname: pdf\n---\nbody\n", encoding="utf-8")
    _write_catalog(
        manifest,
        [
            {"name": "pdf", "description": "fill forms", "tags": ["pdf"], "url": str(skill_md)},
            {"name": "video", "description": "edit video", "tags": ["video"], "url": str(skill_md)},
        ],
    )
    hits = await CatalogSource(str(manifest)).search("pdf")
    assert [hit.name for hit in hits] == ["pdf"]


async def test_catalog_fetch_reads_entry_url(tmp_path: Path) -> None:
    manifest = tmp_path / "catalog.json"
    skill_md = tmp_path / "pdf.md"
    skill_md.write_text("---\nname: pdf\n---\nbody\n", encoding="utf-8")
    _write_catalog(manifest, [{"name": "pdf", "description": "d", "url": str(skill_md)}])
    source = CatalogSource(str(manifest))
    bundle = await source.fetch((await source.search("pdf"))[0])
    assert bundle.files["SKILL.md"].decode().startswith("---")


async def test_catalog_missing_manifest_searches_empty(tmp_path: Path) -> None:
    assert await CatalogSource(str(tmp_path / "nope.json")).search("pdf") == []

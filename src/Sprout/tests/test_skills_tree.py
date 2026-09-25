"""Recursive local scan (``skills/sources/tree.py``).

``LocalDirSource`` looks one level deep, which is right for ``~/.sprout/skills``
and wrong for a foreign directory: a cloned skills repository is nested several
levels down, and a one-level scan reports that as "no skill named X" rather than
as a path problem. These tests pin the walk, and in particular the pruning rule —
a directory holding a ``SKILL.md`` is one skill, so its own vendored
``assets/SKILL.md`` must not be counted as a second one.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.sources.tree import PRUNE_DIRNAMES, scan_tree


def _skill(root: Path, *parts: str, name: str = "", body: str = "Do it.") -> Path:
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    folder.joinpath("SKILL.md").write_text(
        f"---\nname: {name or folder.name}\ndescription: d\n---\n{body}\n", encoding="utf-8"
    )
    return folder


def test_finds_skills_at_any_depth(tmp_path: Path) -> None:
    _skill(tmp_path, "top")
    _skill(tmp_path, "skills", "writing", "docs")
    _skill(tmp_path, "src", "tool")

    found, warnings = scan_tree(tmp_path)

    assert warnings == []
    assert [item.name for item in found] == ["docs", "tool", "top"]


def test_a_skill_root_is_not_searched_for_more_skills(tmp_path: Path) -> None:
    """The pruning rule: one directory holding SKILL.md is one skill."""
    folder = _skill(tmp_path, "pdf", name="pdf")
    (folder / "assets").mkdir()
    (folder / "assets" / "SKILL.md").write_text(
        "---\nname: assets\ndescription: d\n---\nbody\n", encoding="utf-8"
    )

    found, _ = scan_tree(tmp_path)

    assert [item.name for item in found] == ["pdf"]


def test_pointing_at_a_single_skill_directory_finds_it(tmp_path: Path) -> None:
    """``import <one skill folder>`` is the single-skill case, not an empty scan."""
    folder = _skill(tmp_path, "solo", name="solo")

    found, _ = scan_tree(folder)

    assert [item.name for item in found] == ["solo"]


def test_toml_files_are_collected_beside_directories(tmp_path: Path) -> None:
    _skill(tmp_path, "adir", name="adir")
    (tmp_path / "flat.toml").write_text(
        'name = "flat"\ninstructions = "x"\n', encoding="utf-8"
    )

    found, _ = scan_tree(tmp_path)

    assert [item.name for item in found] == ["adir", "flat"]


def test_vendored_and_bookkeeping_directories_are_skipped(tmp_path: Path) -> None:
    for dirname in ("node_modules", ".git", ".venv", "__pycache__", ".fetched", ".hub"):
        _skill(tmp_path, dirname, "hidden")
    _skill(tmp_path, "real", name="real")

    found, _ = scan_tree(tmp_path)

    assert [item.name for item in found] == ["real"]
    assert "node_modules" in PRUNE_DIRNAMES


def test_exclude_keeps_the_walk_out_of_its_own_destination(tmp_path: Path) -> None:
    """``import .`` with the destination inside the source would double-count."""
    _skill(tmp_path, "src", "real")
    dest = tmp_path / "dest"
    _skill(dest, "already-imported")

    found, _ = scan_tree(tmp_path, exclude=[dest])

    assert [item.name for item in found] == ["real"]


def test_depth_cap_is_honoured(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "b", "c", "deep")
    (tmp_path / "shallow").mkdir()
    _skill(tmp_path, "shallow", name="shallow")

    found, _ = scan_tree(tmp_path, max_depth=1)

    assert [item.name for item in found] == ["shallow"]


def test_a_malformed_skill_is_warned_about_and_does_not_abort_the_scan(
    tmp_path: Path,
) -> None:
    _skill(tmp_path, "good", name="good")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("---\nname: broken\n---\n", encoding="utf-8")

    found, warnings = scan_tree(tmp_path)

    assert [item.name for item in found] == ["good"]
    assert len(warnings) == 1
    assert warnings[0].path.name == "SKILL.md"


def test_a_missing_root_is_empty_not_an_error(tmp_path: Path) -> None:
    found, warnings = scan_tree(tmp_path / "nope")

    assert found == []
    assert warnings == []

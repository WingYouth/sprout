"""Skill index + matcher tests (design §7.2 / §7.5)."""

from __future__ import annotations

import json
from pathlib import Path

from Sprout.skills.index import INDEX_VERSION, SkillIndex
from Sprout.skills.matcher import SkillMatcher
from Sprout.skills.models import SkillRecord


def _record(name: str, **overrides: object) -> SkillRecord:
    base: dict[str, object] = {
        "version": "1",
        "description": "",
        "tags": (),
        "source": "local",
        "trust": "trusted",
        "enabled": True,
        "pinned": False,
        "path": "",
        "updated_at": "t",
    }
    base.update(overrides)
    return SkillRecord(name=name, **base)  # type: ignore[arg-type]


# -- index io ------------------------------------------------------------------


def test_index_missing_file_reads_empty(tmp_path: Path) -> None:
    assert SkillIndex(tmp_path / "hub" / "index.json").load() == []


def test_index_save_then_load_round_trips(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "index.json")
    index.save([_record("b"), _record("a")])
    assert [r.name for r in index.load()] == ["b", "a"]


def test_index_file_is_versioned_json(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    SkillIndex(path).save([_record("a")])
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == INDEX_VERSION
    assert "generated_at" in raw
    assert raw["skills"][0]["name"] == "a"


def test_index_corrupt_file_reads_empty(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text("{not json", encoding="utf-8")
    assert SkillIndex(path).load() == []


def test_index_upsert_replaces_and_sorts(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "index.json")
    index.save([_record("b"), _record("c")])
    index.upsert(_record("a", version="2"))
    index.upsert(_record("b", version="9"))
    assert [r.name for r in index.load()] == ["a", "b", "c"]
    record = index.get("b")
    assert record is not None and record.version == "9"


def test_index_remove(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "index.json")
    index.save([_record("a"), _record("b")])
    assert index.remove("a") is True
    assert index.remove("nope") is False
    assert [r.name for r in index.load()] == ["b"]


def test_index_list_filters(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "index.json")
    index.save(
        [
            _record("a", source="catalog", trust="trusted"),
            _record("b", source="github", trust="quarantined"),
            _record("c", source="catalog", trust="trusted", enabled=False),
        ]
    )
    assert [r.name for r in index.list(source="catalog")] == ["a", "c"]
    assert [r.name for r in index.list(trust="quarantined")] == ["b"]
    assert [r.name for r in index.list(enabled_only=True)] == ["a", "b"]


# -- rebuild -------------------------------------------------------------------


def test_rebuild_scans_toml_and_skill_md(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    (root / "alpha.toml").write_text(
        'name = "alpha"\nversion = "1.0"\ninstructions = "do alpha"\n', encoding="utf-8"
    )
    beta = root / "beta"
    beta.mkdir()
    (beta / "SKILL.md").write_text("---\nname: beta\n---\nBody for beta\n", encoding="utf-8")

    records = SkillIndex(tmp_path / "index.json").rebuild(root)
    assert {r.name for r in records} == {"alpha", "beta"}
    paths = {r.name: r.path for r in records}
    assert paths["alpha"].endswith("alpha.toml")
    assert paths["beta"].endswith("beta")


def test_rebuild_ignores_hub_and_quarantine(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    (root / ".hub").mkdir(parents=True)
    (root / ".hub" / "index.json").write_text("{}", encoding="utf-8")
    quarantined = root / ".quarantine" / "evil"
    quarantined.mkdir(parents=True)
    (quarantined / "SKILL.md").write_text("---\nname: evil\n---\nbad\n", encoding="utf-8")
    (root / "good.toml").write_text(
        'name = "good"\nversion = "1"\ninstructions = "ok"\n', encoding="utf-8"
    )
    records = SkillIndex(tmp_path / "idx.json").rebuild(root)
    assert [r.name for r in records] == ["good"]


# -- matcher -------------------------------------------------------------------


def test_matcher_exact_name(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "i.json")
    index.save([_record("pdf-form-filler", description="fill forms")])
    hits = SkillMatcher().match("pdf-form-filler", index)
    assert hits and hits[0].record.name == "pdf-form-filler"
    assert "name" in hits[0].matched_on


def test_matcher_tag_hit(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "i.json")
    index.save([_record("a", tags=("pdf", "form")), _record("b", tags=("video",))])
    hits = SkillMatcher().match("fill a pdf", index)
    assert [h.record.name for h in hits] == ["a"]


def test_matcher_no_match_returns_empty(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "i.json")
    index.save([_record("a", tags=("pdf",), description="pdf work")])
    assert SkillMatcher().match("quantum chromodynamics", index) == []


def test_matcher_skips_untrusted_and_disabled(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "i.json")
    index.save(
        [
            _record("a", tags=("pdf",), trust="quarantined"),
            _record("b", tags=("pdf",), enabled=False),
            _record("c", tags=("pdf",)),
        ]
    )
    hits = SkillMatcher().match("pdf", index)
    assert [h.record.name for h in hits] == ["c"]


def test_matcher_respects_limit_and_order(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / "i.json")
    index.save(
        [
            _record("pdf", tags=("pdf",), description="pdf pdf pdf"),
            _record("other", description="pdf helper"),
        ]
    )
    hits = SkillMatcher().match("pdf", index, limit=1)
    assert len(hits) == 1
    assert hits[0].record.name == "pdf"

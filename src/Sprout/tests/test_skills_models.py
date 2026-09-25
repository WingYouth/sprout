"""Skill model tests (design §4.1 / §4.2): defaults, provenance, index entry.

S0 guard: the historical five-field shape and its defaults must be untouched,
and the added fields must be inert for existing callers.
"""

from __future__ import annotations

from Sprout.skills.models import Skill, SkillRecord, SkillSource, TrustLevel

# -- historical shape ----------------------------------------------------------


def test_skill_keeps_historical_shape() -> None:
    skill = Skill(name="pdf", version="1.0.0", instructions="do it")
    assert skill.required_tools == ()
    assert skill.enabled is True


def test_skill_new_fields_default_to_noop() -> None:
    skill = Skill(name="pdf", version="1.0.0", instructions="do it")
    assert skill.description == ""
    assert skill.tags == ()
    assert skill.source == SkillSource.LOCAL.value
    assert skill.origin == ""
    assert skill.digest == ""
    assert skill.trust == TrustLevel.UNTRUSTED.value
    assert skill.requires_toolsets == ()
    assert skill.fallback_for_toolsets == ()
    assert skill.pinned is False


def test_skill_is_frozen() -> None:
    skill = Skill(name="pdf", version="1.0.0", instructions="do it")
    try:
        skill.name = "other"  # type: ignore[misc]
    except Exception as exc:  # FrozenInstanceError
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()
    else:  # pragma: no cover - would mean the dataclass is mutable
        raise AssertionError("Skill must be immutable")


# -- trust model ---------------------------------------------------------------


def test_trust_level_gates_injection() -> None:
    assert TrustLevel.TRUSTED.injectable is True
    for level in (TrustLevel.UNTRUSTED, TrustLevel.QUARANTINED, TrustLevel.REJECTED):
        assert level.injectable is False


# -- index entry ---------------------------------------------------------------


def test_skill_record_from_skill_projects_index_fields() -> None:
    skill = Skill(
        name="pdf",
        version="1.2.0",
        instructions="a very long body",
        description="fill pdf forms",
        tags=("pdf", "form"),
        source=SkillSource.CATALOG.value,
        origin="https://example.test/pdf",
        digest="sha256:abc",
        trust=TrustLevel.TRUSTED.value,
        pinned=True,
    )
    record = SkillRecord.from_skill(skill, path="/tmp/pdf", updated_at="2026-09-22T00:00:00Z")
    assert record.name == "pdf"
    assert record.version == "1.2.0"
    assert record.description == "fill pdf forms"
    assert record.tags == ("pdf", "form")
    assert record.source == "catalog"
    assert record.origin == "https://example.test/pdf"
    assert record.digest == "sha256:abc"
    assert record.trust == "trusted"
    assert record.pinned is True
    assert record.path == "/tmp/pdf"


def test_skill_record_excludes_instructions() -> None:
    """L0 must stay small: the index entry never carries the full body."""
    skill = Skill(name="pdf", version="1", instructions="secret body")
    record = SkillRecord.from_skill(skill)
    assert not hasattr(record, "instructions")
    assert "instructions" not in record.to_dict()


def test_skill_record_round_trips_through_dict() -> None:
    record = SkillRecord(
        name="x",
        version="1",
        description="d",
        tags=("a", "b"),
        source="github",
        origin="owner/repo",
        digest="sha256:z",
        trust="quarantined",
        enabled=False,
        pinned=True,
        path="/p",
        updated_at="t",
    )
    assert SkillRecord.from_dict(record.to_dict()) == record


def test_skill_record_from_dict_tolerates_missing_keys() -> None:
    record = SkillRecord.from_dict({"name": "only-name"})
    assert record.name == "only-name"
    assert record.version == ""
    assert record.description == ""
    assert record.tags == ()
    assert record.source == "local"
    assert record.trust == "untrusted"
    assert record.enabled is True
    assert record.pinned is False

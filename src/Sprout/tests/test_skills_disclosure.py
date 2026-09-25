"""Progressive disclosure tests (design §6.1): L0 index, trust + activation gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from Sprout.context.context import AgentContext
from Sprout.session.models import Session
from Sprout.skills.models import Skill, SkillSource, TrustLevel


def _skill(name: str, **overrides: object) -> Skill:
    base: dict[str, object] = {
        "version": "1.0",
        "instructions": f"Long body for {name}\nsecond line",
        "enabled": True,
        "description": "",
        "tags": (),
        "source": SkillSource.LOCAL.value,
        "trust": TrustLevel.TRUSTED.value,
    }
    base.update(overrides)
    return Skill(name=name, **base)  # type: ignore[arg-type]


def _ctx(
    skills: Sequence[Skill],
    *,
    tools: Mapping[str, object] | None = None,
    disclosure: str = "progressive",
) -> AgentContext:
    return AgentContext(
        session=Session(id="s1", user_id="u1"),
        user={"id": "u1"},
        skills={skill.name: skill for skill in skills},
        tools=tools or {},  # type: ignore[arg-type]
        skill_disclosure=disclosure,
    )


# -- L0 index ------------------------------------------------------------------


def test_index_lists_visible_skills_with_summary() -> None:
    ctx = _ctx([_skill("pdf", description="fill pdf forms", tags=("pdf", "form"))])
    text = ctx.skills_index()
    assert "pdf" in text
    assert "fill pdf forms" in text
    assert "tags: pdf, form" in text


def test_index_falls_back_to_first_body_line() -> None:
    ctx = _ctx([_skill("alpha", instructions="First line here\nmore detail")])
    assert "First line here" in ctx.skills_index()
    assert "more detail" not in ctx.skills_index()


def test_index_prefers_description_over_body() -> None:
    ctx = _ctx(
        [_skill("alpha", description="short summary", instructions="SECRET BODY CONTENT")]
    )
    text = ctx.skills_index()
    assert "short summary" in text
    assert "SECRET BODY CONTENT" not in text


def test_index_only_carries_first_body_line() -> None:
    ctx = _ctx([_skill("alpha", instructions="Summary line\nSECRET BODY CONTENT")])
    text = ctx.skills_index()
    assert "Summary line" in text
    assert "SECRET BODY CONTENT" not in text


def test_index_empty_when_no_visible_skills() -> None:
    assert _ctx([]).skills_index() == ""


# -- trust gate ----------------------------------------------------------------


def test_untrusted_skill_is_hidden() -> None:
    ctx = _ctx([_skill("dl", trust=TrustLevel.UNTRUSTED.value)])
    assert ctx.skills_index() == ""
    assert ctx.visible_skills() == ()


def test_quarantined_skill_is_hidden() -> None:
    assert _ctx([_skill("dl", trust=TrustLevel.QUARANTINED.value)]).skills_index() == ""


def test_disabled_skill_is_hidden() -> None:
    assert _ctx([_skill("off", enabled=False)]).skills_index() == ""


# -- conditional activation ----------------------------------------------------


def test_requires_tools_hides_skill_until_present() -> None:
    skill = _skill("net", requires_toolsets=("http_get",))
    assert _ctx([skill]).skills_index() == ""
    assert "net" in _ctx([skill], tools={"http_get": object()}).skills_index()


def test_fallback_hidden_when_replacement_present() -> None:
    skill = _skill("legacy", fallback_for_toolsets=("http_get",))
    assert "legacy" in _ctx([skill]).skills_index()
    assert _ctx([skill], tools={"http_get": object()}).skills_index() == ""


# -- eager mode / defaults -----------------------------------------------------


def test_eager_mode_keeps_full_body() -> None:
    ctx = _ctx([_skill("alpha", instructions="FULL BODY")], disclosure="eager")
    assert "FULL BODY" in ctx.skill_instructions()
    assert ctx.skill_disclosure == "eager"


def test_default_disclosure_is_progressive() -> None:
    assert _ctx([]).skill_disclosure == "progressive"

"""Agent-facing skill tools (design §6.1): skill_view / skill_search / skill_install."""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.index import SkillIndex
from Sprout.skills.models import Skill, SkillRecord
from Sprout.skills.resolver import SkillResolver
from Sprout.skills.sources.base import SkillStub
from Sprout.skills.tools import SkillInstallTool, SkillSearchTool, SkillViewTool

SKILL_MD = "---\nname: pdf\ndescription: fill pdf forms\n---\nFull instructions here.\n"


def _skill_dir(tmp_path: Path, name: str = "pdf") -> Path:
    folder = tmp_path / name
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (folder / "references" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (folder / "secret-outside.txt")  # not used; keeps the dir listing deterministic
    return folder


def _skill(folder: Path, **kwargs: object) -> Skill:
    return Skill(
        name=str(kwargs.pop("name", "pdf")),
        version="1.0",
        instructions="Full instructions here.",
        description="fill pdf forms",
        trust="trusted",
        origin=str(folder),
        **kwargs,
    )


# -- skill_view: the L1/L2 half of progressive disclosure ----------------------


async def test_view_returns_the_full_body(tmp_path: Path) -> None:
    tool = SkillViewTool({"pdf": _skill(_skill_dir(tmp_path))})

    result = await tool.invoke({"name": "pdf"})

    assert result.ok
    assert "Full instructions here." in result.content
    assert "# Skill: pdf" in result.content


async def test_view_reads_a_file_inside_the_skill(tmp_path: Path) -> None:
    tool = SkillViewTool({"pdf": _skill(_skill_dir(tmp_path))})

    result = await tool.invoke({"name": "pdf", "path": "references/notes.md"})

    assert result.ok
    assert "# notes" in result.content


async def test_view_refuses_path_traversal(tmp_path: Path) -> None:
    folder = _skill_dir(tmp_path)
    (tmp_path / "outside.txt").write_text("do not read me", encoding="utf-8")
    tool = SkillViewTool({"pdf": _skill(folder)})

    result = await tool.invoke({"name": "pdf", "path": "../outside.txt"})

    assert not result.ok
    assert "escapes" in (result.error or "")


async def test_view_reports_unknown_skill_with_the_known_ones(tmp_path: Path) -> None:
    tool = SkillViewTool({"pdf": _skill(_skill_dir(tmp_path))})

    result = await tool.invoke({"name": "nope"})

    assert not result.ok
    assert "pdf" in (result.error or "")


async def test_view_rejects_a_blank_name(tmp_path: Path) -> None:
    tool = SkillViewTool({})
    assert not (await tool.invoke({"name": "  "})).ok


async def test_view_reads_through_a_provider_so_new_skills_appear(tmp_path: Path) -> None:
    """A skill installed mid-session must be viewable without rebuilding the tool."""
    folder = _skill_dir(tmp_path)
    installed: dict[str, Skill] = {}
    tool = SkillViewTool(lambda: installed)

    assert not (await tool.invoke({"name": "pdf"})).ok
    installed["pdf"] = _skill(folder)
    assert (await tool.invoke({"name": "pdf"})).ok


async def test_view_reports_a_missing_file(tmp_path: Path) -> None:
    tool = SkillViewTool({"pdf": _skill(_skill_dir(tmp_path))})
    result = await tool.invoke({"name": "pdf", "path": "references/nope.md"})
    assert not result.ok
    assert "No such file" in (result.error or "")


# -- skill_search -------------------------------------------------------------


def _index_with(tmp_path: Path, **overrides: object) -> SkillIndex:
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save(
        [
            SkillRecord(
                name=str(overrides.pop("name", "pdf")),
                version="1.0",
                description=str(overrides.pop("description", "fill pdf forms")),
                trust=str(overrides.pop("trust", "trusted")),
                tags=tuple(overrides.pop("tags", ())),
            )
        ]
    )
    return index


async def test_search_reports_a_local_hit(tmp_path: Path) -> None:
    resolver = SkillResolver(index=_index_with(tmp_path))
    tool = SkillSearchTool(resolver)

    result = await tool.invoke({"query": "fill a pdf"})

    assert result.ok
    assert "Installed skills matching" in result.content
    assert result.data["installed"][0]["name"] == "pdf"


async def test_search_lists_candidates_without_installing(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save([])

    class Source:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            return [
                SkillStub(
                    name="pdf",
                    source="catalog",
                    origin="https://cat.test/pdf/SKILL.md",
                    description="fill pdf",
                    install_command="npx skills add acme/pdf",
                )
            ]

        async def fetch(self, stub: SkillStub):  # pragma: no cover - not called
            raise AssertionError("search must not fetch")

    tool = SkillSearchTool(SkillResolver(index=index, sources=[Source()]))
    result = await tool.invoke({"query": "pdf", "crawl": True})

    assert result.ok
    assert "not installed" in result.content
    assert "npx skills add acme/pdf" in result.content
    assert result.data["candidates"][0]["install_command"] == "npx skills add acme/pdf"


async def test_search_rejects_a_blank_query(tmp_path: Path) -> None:
    tool = SkillSearchTool(SkillResolver(index=_index_with(tmp_path)))
    assert not (await tool.invoke({"query": " "})).ok


# -- skill_install: approval-gated -------------------------------------------


def test_install_is_high_risk_so_it_needs_approval() -> None:
    """The tool must never be auto-approved: third-party instructions (§8.4)."""
    tool = SkillInstallTool(SkillResolver(index=SkillIndex("unused.json")))  # type: ignore[arg-type]
    assert tool.spec.risk_level == "high"


async def test_install_surfaces_a_pending_approval_as_needs_approval(tmp_path: Path) -> None:
    from Sprout.security.access import AccessDecision
    from Sprout.skills.broker import InstallOutcome, InstallReport

    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save([])

    class Source:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            return [SkillStub(name="pdf", source="catalog", origin="https://cat.test/pdf")]

        async def fetch(self, stub: SkillStub):  # pragma: no cover - broker stubbed
            raise AssertionError

    class Broker:
        async def install(self, stub, source, *, skills_dir, **kwargs) -> InstallReport:
            return InstallReport(
                name=stub.name,
                source=stub.source,
                outcome=InstallOutcome(
                    AccessDecision.REQUIRE_APPROVAL, "needs a human", approval_id="ap-1"
                ),
                quarantined_path=str(tmp_path / "q" / "pdf"),
            )

    resolver = SkillResolver(
        index=index,
        sources=[Source()],
        broker=Broker(),  # type: ignore[arg-type]
        skills_dir=tmp_path / "skills",
    )
    result = await SkillInstallTool(resolver).invoke({"name": "pdf", "source": "catalog"})

    assert result.ok is False
    assert result.approval_id == "ap-1"
    assert "approval" in result.to_text()


async def test_install_reports_an_unknown_skill(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save([])
    resolver = SkillResolver(index=index, sources=[], skills_dir=tmp_path / "skills")

    result = await SkillInstallTool(resolver).invoke({"name": "ghost"})

    assert not result.ok
    assert "No skill named" in (result.error or "")


async def test_install_requires_a_name(tmp_path: Path) -> None:
    resolver = SkillResolver(index=SkillIndex(tmp_path / "i.json"), skills_dir=tmp_path)
    assert not (await SkillInstallTool(resolver).invoke({"name": ""})).ok


async def test_install_reports_when_installation_is_not_configured(tmp_path: Path) -> None:
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save([])

    class Source:
        name = "catalog"

        async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
            return [SkillStub(name="pdf", source="catalog", origin="https://cat.test/pdf")]

        async def fetch(self, stub: SkillStub):  # pragma: no cover - never reached
            raise AssertionError

    resolver = SkillResolver(index=index, sources=[Source()])

    result = await SkillInstallTool(resolver).invoke({"name": "pdf"})

    assert not result.ok
    # The message must distinguish "found it, cannot install here" from
    # "no such skill", so a missing broker is never mistaken for a typo.
    error = result.error or ""
    assert "cannot install it" in error
    assert "no install broker" in error

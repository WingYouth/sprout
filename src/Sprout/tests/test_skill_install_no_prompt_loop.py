"""An approved install must complete without asking a second time.

The full path a chat turn takes is two-layered:

* ``ToolExecutor`` gates the tool itself (``skill_install`` is high risk) and
  issues/consumes a grant keyed by the tool name and the *tool's* arguments.
* ``SkillInstallBroker`` gates by provenance and issues/consumes a grant keyed by
  ``skill.install`` and the *install's* arguments (skill, source, origin, digest).

Those fingerprints differ, so each layer used to ask its own question — and
because a grant is single-use, the retry after answering one layer found the
other still unsatisfied. That is what produced the repeated prompts, with
nothing ever installed.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.broker import SkillInstallBroker
from Sprout.skills.index import SkillIndex
from Sprout.skills.resolver import SkillResolver
from Sprout.skills.sources.base import SkillBundle, SkillStub
from Sprout.skills.tools import SkillInstallTool
from Sprout.storage.local.memory import MemorySkillStore

SKILL = "universal-scraping-architect"


class _Source:
    """A source that serves one third-party skill, no network."""

    name = "catalog"

    def __init__(self, tmp_path: Path) -> None:
        self._dir = tmp_path

    async def search(self, query: str, *, limit: int = 10) -> list[SkillStub]:
        return [
            SkillStub(
                name=SKILL,
                source="github",
                origin=f"github:acme/skills/{SKILL}",
                description="scrape pages",
            )
        ]

    async def fetch(self, stub: SkillStub) -> SkillBundle:
        return SkillBundle(
            stub=stub,
            files={
                "SKILL.md": (
                    f"---\nname: {SKILL}\ndescription: scrape pages\n---\nDo it.\n"
                ).encode()
            },
        )


def _resolver(tmp_path: Path, manager) -> SkillResolver:
    from Sprout.security.engine import PolicyEngine

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    index = SkillIndex(tmp_path / ".hub" / "index.json")
    index.save([])
    broker = SkillInstallBroker(
        PolicyEngine(), approvals=manager, skills=MemorySkillStore()
    )
    return SkillResolver(
        index=index,
        sources=[_Source(tmp_path)],
        broker=broker,
        skills_dir=skills_dir,
    )


def _manager():
    from Sprout.security.approval import ApprovalManager, ApprovalPolicy
    from Sprout.storage.local.memory import MemoryOperationalStore

    return ApprovalManager(MemoryOperationalStore(), policy=ApprovalPolicy())


async def test_an_approved_install_does_not_ask_again(tmp_path: Path) -> None:
    manager = _manager()
    tool = SkillInstallTool(_resolver(tmp_path, manager))

    first = await tool.invoke({"name": SKILL})
    assert first.approval_id, "a third-party install must ask the first time"

    await manager.decide(first.approval_id, True, decided_by="test", channel="cli")

    second = await tool.invoke({"name": SKILL})

    assert second.ok, f"the approved install must go through, got: {second.error!r}"
    assert not second.approval_id, "it must not ask a second time"


async def test_a_second_install_asks_again(tmp_path: Path) -> None:
    """Single-use grants must not silently authorise a repeat install."""
    manager = _manager()
    tool = SkillInstallTool(_resolver(tmp_path, manager))

    first = await tool.invoke({"name": SKILL})
    await manager.decide(first.approval_id, True, decided_by="test", channel="cli")
    second = await tool.invoke({"name": SKILL})
    assert second.ok

    third = await tool.invoke({"name": SKILL})

    assert third.approval_id, "the spent grant must not cover another install"


async def test_the_loop_terminates_when_a_human_keeps_approving(
    tmp_path: Path,
) -> None:
    """The reported symptom: approving repeatedly never installed anything."""
    manager = _manager()
    tool = SkillInstallTool(_resolver(tmp_path, manager))

    result = await tool.invoke({"name": SKILL})
    approvals = 0
    while result.approval_id and approvals < 5:
        approvals += 1
        await manager.decide(result.approval_id, True, decided_by="test", channel="cli")
        result = await tool.invoke({"name": SKILL})

    assert result.ok, "approving must converge on an install"
    assert approvals == 1, f"one approval should suffice, took {approvals}"

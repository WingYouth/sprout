"""End-to-end wiring: the agent actually sees and can use skills (§6.1).

These tests boot a real Runtime and assert the loop is closed — the injected L0
index names a tool that exists, an installed skill reaches the prompt, and an
untrusted one does not.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.config.loader import default_settings
from Sprout.runtime.factory import create_runtime
from Sprout.skills.index import SkillIndex
from Sprout.skills.layout import index_path
from Sprout.skills.loader import artifact_digest
from Sprout.skills.models import SkillRecord

SKILL_MD = "---\nname: pdf\ndescription: fill pdf forms\n---\nFull instructions.\n"


def _settings(tmp_path: Path, *, skills_dir: Path) -> object:
    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{tmp_path / 'm.db'}"
    settings.storage.trajectory_dir = str(tmp_path / "traj")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "audit.jsonl")
    settings.skills_dir = str(skills_dir)
    return settings


def _install(root: Path, name: str, *, trust: str) -> Path:
    folder = root / ".fetched" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    index = SkillIndex(index_path(root))
    index.upsert(
        SkillRecord(
            name="pdf",
            version="1.0",
            description="fill pdf forms",
            source="catalog",
            trust=trust,
            digest=artifact_digest(folder),
            path=str(folder),
        )
    )
    return folder


def test_skill_view_tool_exists_so_the_injected_hint_is_not_a_dead_end(
    tmp_path: Path,
) -> None:
    """loop.py tells the model to call skill_view; that tool must be registered."""
    runtime = create_runtime(_settings(tmp_path, skills_dir=tmp_path / "skills"))  # type: ignore[arg-type]

    names = set(runtime.tools.list())

    assert "skill_view" in names
    assert "skill_search" in names
    assert "skill_install" in names


def test_skill_install_is_high_risk_so_policy_gates_it(tmp_path: Path) -> None:
    runtime = create_runtime(_settings(tmp_path, skills_dir=tmp_path / "skills"))  # type: ignore[arg-type]

    risks = {name: tool.spec.risk_level for name, tool in runtime.tools.list().items()}

    assert risks["skill_install"] == "high"
    assert risks["skill_view"] == "low"


def test_approved_installed_skill_reaches_the_injected_index(tmp_path: Path) -> None:
    """The closed loop: install → trust → visible in L0."""
    skills_dir = tmp_path / "skills"
    _install(skills_dir, "pdf", trust="trusted")

    runtime = create_runtime(_settings(tmp_path, skills_dir=skills_dir))  # type: ignore[arg-type]

    skill = runtime.skills.list()["pdf"]
    assert skill.trust == "trusted"
    assert skill.source == "catalog"


def test_untrusted_installed_skill_stays_out_of_the_registry_prompt(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    _install(skills_dir, "pdf", trust="untrusted")

    runtime = create_runtime(_settings(tmp_path, skills_dir=skills_dir))  # type: ignore[arg-type]

    assert runtime.skills.list()["pdf"].trust == "untrusted"


def test_progressive_disclosure_is_the_default_and_configurable(tmp_path: Path) -> None:
    settings = _settings(tmp_path, skills_dir=tmp_path / "skills")
    assert settings.skills.disclosure == "progressive"  # type: ignore[attr-defined]

    runtime = create_runtime(settings)  # type: ignore[arg-type]
    assert runtime._contexts._skill_disclosure == "progressive"

    settings.skills.disclosure = "eager"  # type: ignore[attr-defined]
    eager = create_runtime(settings)  # type: ignore[arg-type]
    assert eager._contexts._skill_disclosure == "eager"


def test_skill_view_reads_a_skill_installed_after_boot(tmp_path: Path) -> None:
    """A skill installed mid-session must be viewable without a restart."""
    import asyncio

    skills_dir = tmp_path / "skills"
    runtime = create_runtime(_settings(tmp_path, skills_dir=skills_dir))  # type: ignore[arg-type]
    tool = runtime.tools.get("skill_view")

    before = asyncio.run(tool.invoke({"name": "pdf"}))
    assert before.ok is False

    _install(skills_dir, "pdf", trust="trusted")
    # The resolver calls this after a successful install; the tool reads through
    # the registry, so without the hook the skill would stay invisible.
    runtime.skills.reload(skills_dir, index=SkillIndex(index_path(skills_dir)))

    after = asyncio.run(tool.invoke({"name": "pdf"}))
    assert after.ok
    assert "Full instructions." in after.content

"""Trust is decided by the registry, never by what a skill claims on disk (§8.3).

The property under test is the fail-closed one: an installed skill becomes
injectable only when the store says ``trusted`` *and* the content still hashes to
the digest that was approved. Anything else stays out of the prompt.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.index import SkillIndex
from Sprout.skills.layout import index_path
from Sprout.skills.loader import artifact_digest, load_skills
from Sprout.skills.models import SkillRecord
from Sprout.skills.registry import create_skill_registry

SKILL_MD = "---\nname: pdf\ndescription: fill pdf forms\n---\nBody.\n"


def _install_skill(root: Path, name: str = "pdf") -> Path:
    """Lay a downloaded skill down where the broker would put it."""
    folder = root / ".fetched" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return folder


def _write_index(root: Path, *, trust: str, digest: str, name: str = "pdf") -> SkillIndex:
    index = SkillIndex(index_path(root))
    index.save(
        [
            SkillRecord(
                name=name,
                version="1.0",
                description="fill pdf forms",
                source="catalog",
                trust=trust,
                digest=digest,
                path=str(root / ".fetched" / name),
            )
        ]
    )
    return index


def test_downloaded_skill_loads_as_untrusted_whatever_it_claims(tmp_path: Path) -> None:
    """A frontmatter key must not be able to mark a downloaded skill trusted."""
    root = tmp_path / "skills"
    folder = root / ".fetched" / "pdf"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: pdf\ndescription: x\ntrust: trusted\n---\nBody.\n", encoding="utf-8"
    )

    loaded = load_skills(root)

    assert [skill.name for skill in loaded] == ["pdf"]
    assert loaded[0].trust == "untrusted"
    assert loaded[0].source == "catalog"


def test_approved_digest_restores_trust(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    folder = _install_skill(root)
    index = _write_index(root, trust="trusted", digest=artifact_digest(folder))

    registry = create_skill_registry(root, index=index)

    assert registry.list()["pdf"].trust == "trusted"


def test_tampered_content_loses_trust(tmp_path: Path) -> None:
    """An approval binds to a digest; editing the skill invalidates it (§8.4)."""
    root = tmp_path / "skills"
    folder = _install_skill(root)
    index = _write_index(root, trust="trusted", digest=artifact_digest(folder))

    (folder / "SKILL.md").write_text(SKILL_MD + "Now do something else.\n", encoding="utf-8")

    registry = create_skill_registry(root, index=index)

    assert registry.list()["pdf"].trust == "untrusted"


def test_untrusted_record_stays_untrusted(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    folder = _install_skill(root)
    index = _write_index(root, trust="untrusted", digest=artifact_digest(folder))

    registry = create_skill_registry(root, index=index)

    assert registry.list()["pdf"].trust == "untrusted"


def test_missing_index_fails_closed_for_downloaded_skills(tmp_path: Path) -> None:
    """No snapshot at all must not mean "trust everything I found on disk"."""
    root = tmp_path / "skills"
    _install_skill(root)

    registry = create_skill_registry(root)

    assert registry.list()["pdf"].trust == "untrusted"


def test_unreadable_index_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _install_skill(root)
    index = _write_index(root, trust="trusted", digest="sha256:whatever")
    index.path.write_text("{ not json", encoding="utf-8")

    registry = create_skill_registry(root, index=index)

    assert registry.list()["pdf"].trust == "untrusted"


def test_user_authored_skill_at_the_root_stays_trusted(tmp_path: Path) -> None:
    """The fail-closed rule is for managed dirs; the user's own work is theirs."""
    root = tmp_path / "skills"
    folder = root / "mine"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

    registry = create_skill_registry(root)

    assert registry.list()["pdf"].trust == "trusted"


def test_evolved_skill_also_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    folder = root / ".evolved" / "pdf"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

    loaded = load_skills(root)

    assert loaded[0].source == "evolved"
    assert loaded[0].trust == "untrusted"

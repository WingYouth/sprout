"""End-to-end install tests (design §7.4/§10): fetch → scan → decide → promote → register."""

from __future__ import annotations

import json
from pathlib import Path

from Sprout.security.approval import ApprovalManager
from Sprout.security.engine import PolicyEngine
from Sprout.security.layered_policy import LayeredPolicyEngine
from Sprout.skills.broker import SkillInstallBroker
from Sprout.skills.layout import index_path, quarantine_dir
from Sprout.skills.sources.local import LocalDirSource
from Sprout.storage.local.memory import MemoryOperationalStore, MemorySkillStore


def _engine() -> LayeredPolicyEngine:
    return LayeredPolicyEngine(PolicyEngine())


def _write_skill(root: Path, name: str, description: str, body: str = "Do it.") -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )


async def test_install_first_party_lands_in_skills_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming"
    _write_skill(source_dir, "pdf", "fill pdf forms")
    skills_dir = tmp_path / "skills"

    store = MemorySkillStore()
    broker = SkillInstallBroker(_engine(), skills=store)
    source = LocalDirSource(source_dir, source="local")
    report = await broker.install((await source.search("pdf"))[0], source, skills_dir=skills_dir)

    assert report.installed
    assert (Path(report.installed_path) / "SKILL.md").is_file()
    # a user-authored skill lands in place at the skills root (§8.1)
    assert Path(report.installed_path) == skills_dir / "pdf"
    # quarantine is emptied on success
    assert not (quarantine_dir(skills_dir) / "pdf").exists()
    # ...and the install is registered in the store, trusted by digest (§10)
    assert report.record is not None
    assert report.record.trust == "trusted"
    assert await store.is_trusted("pdf", report.record.digest)
    # changed content means a different digest, so it must be re-reviewed (§8.4)
    assert await store.is_trusted("pdf", "sha256:changed") is False
    # index.json is written from the registry as a derived snapshot (§10.4)
    snapshot = json.loads(index_path(skills_dir).read_text(encoding="utf-8"))
    assert [entry["name"] for entry in snapshot["skills"]] == ["pdf"]


async def test_install_catalog_stays_in_quarantine_pending_approval(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming"
    _write_skill(source_dir, "pdf", "fill pdf forms")
    skills_dir = tmp_path / "skills"

    approvals = ApprovalManager(MemoryOperationalStore())
    store = MemorySkillStore()
    broker = SkillInstallBroker(_engine(), approvals=approvals, skills=store)
    source = LocalDirSource(source_dir, source="catalog")
    report = await broker.install((await source.search("pdf"))[0], source, skills_dir=skills_dir)

    assert report.pending_approval
    assert not report.installed
    assert Path(report.quarantined_path).is_dir()
    assert not (skills_dir / "pdf").exists()
    # nothing awaiting approval reaches the registry
    assert await store.list() == []


async def test_install_fatal_scan_is_rejected_and_not_staged(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming"
    _write_skill(source_dir, "evil", "does bad things", body="-----BEGIN RSA PRIVATE KEY-----")
    skills_dir = tmp_path / "skills"

    store = MemorySkillStore()
    broker = SkillInstallBroker(_engine(), skills=store)
    source = LocalDirSource(source_dir, source="catalog")
    report = await broker.install((await source.search("evil"))[0], source, skills_dir=skills_dir)

    assert report.rejected
    assert not report.installed
    assert not (quarantine_dir(skills_dir) / "evil").exists()
    assert not (skills_dir / "evil").exists()
    assert await store.list() == []

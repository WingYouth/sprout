"""Registry vs disk: the divergence that used to be silent (§7.2, §10.4).

``SkillIndex.rebuild`` scans disk; the registry (``sprout_audit.db``) records
what was installed and approved. Neither is the whole truth, and before this
they were never compared: a rebuild simply overwrote the snapshot with whatever
disk held, so a registry row whose files had gone disappeared from the index
while ``skills list`` kept showing it from the store. The operator saw a
consistent picture and the model saw a different one.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.index import SkillIndex, reconcile
from Sprout.skills.layout import index_path
from Sprout.skills.loader import artifact_digest
from Sprout.skills.models import SkillRecord, TrustLevel
from Sprout.skills.registry import create_skill_registry
from Sprout.storage.local.memory import MemorySkillStore


def _record(name: str, path: Path | str = "", **overrides: object) -> SkillRecord:
    base: dict[str, object] = {
        "version": "1",
        "description": "d",
        "source": "local",
        "origin": "",
        "digest": "sha256:x",
        "trust": "trusted",
        "enabled": True,
        "path": str(path),
        "updated_at": "t",
    }
    base.update(overrides)
    return SkillRecord(name=name, **base)  # type: ignore[arg-type]


def _skill_dir(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    return folder


def test_a_registry_row_with_no_files_is_reported_missing(tmp_path: Path) -> None:
    """The exact production case: two rows pointing at deleted directories."""
    skills_dir = tmp_path / "skills"
    present = _skill_dir(skills_dir, "pdf")
    gone = skills_dir / ".fetched" / "deleted-by-hand"

    store = _record_store(
        _record("pdf", present),
        _record("gone", gone),
    )

    report, written = reconcile(store, skills_dir)

    assert [record.name for record in report.missing] == ["gone"]
    assert [record.name for record in report.ok] == ["pdf"]
    assert not report.clean
    # The snapshot lists only what can actually be loaded...
    assert [record.name for record in written] == ["pdf"]
    assert [r.name for r in SkillIndex(index_path(skills_dir)).list()] == ["pdf"]


def test_a_missing_row_is_kept_in_the_registry_not_forgotten(tmp_path: Path) -> None:
    """Dropping it silently is what made the divergence invisible."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    store = _record_store(_record("gone", skills_dir / "nope"))

    reconcile(store, skills_dir)

    assert [record.name for record in _list(store)] == ["gone"]


def test_a_skill_on_disk_with_no_row_is_reported_unregistered(tmp_path: Path) -> None:
    """It loads untrusted, so it is present but invisible to the model."""
    skills_dir = tmp_path / "skills"
    _skill_dir(skills_dir, "copied-in")
    store = _record_store()

    report, written = reconcile(store, skills_dir)

    assert [record.name for record in report.unregistered] == ["copied-in"]
    assert [record.name for record in written] == ["copied-in"]


def test_a_clean_tree_reports_nothing(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    present = _skill_dir(skills_dir, "pdf")
    store = _record_store(_record("pdf", present))

    report, _ = reconcile(store, skills_dir)

    assert report.clean
    assert report.missing == ()
    assert report.unregistered == ()


def test_divergence_is_reported_in_both_directions_at_once(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    both = _skill_dir(skills_dir, "both")
    _skill_dir(skills_dir, "orphan")
    store = _record_store(
        _record("both", both),
        _record("ghost", skills_dir / "vanished"),
    )

    report, _ = reconcile(store, skills_dir)

    assert [r.name for r in report.missing] == ["ghost"]
    assert [r.name for r in report.unregistered] == ["orphan"]
    assert [r.name for r in report.ok] == ["both"]


def test_reconcile_writes_the_snapshot_from_disk(tmp_path: Path) -> None:
    """The snapshot must describe what loads, not what was once installed."""
    skills_dir = tmp_path / "skills"
    present = _skill_dir(skills_dir, "pdf")
    store = _record_store(_record("pdf", present), _record("ghost", skills_dir / "x"))

    reconcile(store, skills_dir)

    snapshot = SkillIndex(index_path(skills_dir)).list()
    assert {record.name for record in snapshot} == {"pdf"}


def test_reconcile_does_not_revoke_an_approved_downloaded_skill(
    tmp_path: Path,
) -> None:
    """A rebuild must not turn an approved download back into an untrusted one.

    Regression: the snapshot was rebuilt from a *disk scan*, and the loader
    force-loads anything under ``.fetched/`` as untrusted — trust is the
    registry's decision, so the scan cannot know any better. The scan's guess
    then became the index's record, and the index is the authority the runtime
    restores trust from. So ``sprout skills index --rebuild`` silently revoked
    the operator's approval of every downloaded and evolved skill: they dropped
    out of the prompt with no error, and the only way back was to approve each
    one again.

    ``reconcile`` has the registry in hand, so it is the one place that can
    carry the recorded trust across instead of discarding it.
    """
    skills_dir = tmp_path / "skills"
    folder = _skill_dir(skills_dir / ".fetched", "downloaded")
    digest = artifact_digest(folder)
    store = _record_store(
        _record("downloaded", folder, source="catalog", trust="trusted", digest=digest)
    )

    # What a successful install leaves behind, and what the runtime restores from.
    _export(store, skills_dir)
    assert _trusted(skills_dir, "downloaded"), "the install did not record trust"

    reconcile(store, skills_dir)

    assert _trusted(skills_dir, "downloaded"), (
        "the rebuild revoked an approval the registry still holds: the skill is "
        "now untrusted and has silently left the prompt"
    )


def test_reconcile_keeps_untrusted_skills_untrusted(tmp_path: Path) -> None:
    """The fix must not become a blanket grant.

    A downloaded skill whose row says untrusted — or whose content changed since
    approval — stays untrusted across a rebuild. Only the recorded decision is
    carried over, and only for the content it was made about.
    """
    skills_dir = tmp_path / "skills"
    folder = _skill_dir(skills_dir / ".fetched", "revoked")
    store = _record_store(
        _record(
            "revoked",
            folder,
            source="catalog",
            trust="untrusted",
            digest=artifact_digest(folder),
        )
    )
    _export(store, skills_dir)

    reconcile(store, skills_dir)

    assert not _trusted(skills_dir, "revoked")


def test_reconcile_downgrades_when_the_content_changed(tmp_path: Path) -> None:
    """Carrying trust over must not carry it onto different bytes (§8.4)."""
    skills_dir = tmp_path / "skills"
    folder = _skill_dir(skills_dir / ".fetched", "edited")
    store = _record_store(
        _record(
            "edited",
            folder,
            source="catalog",
            trust="trusted",
            digest=artifact_digest(folder),
        )
    )
    _export(store, skills_dir)
    assert _trusted(skills_dir, "edited")

    # Edit the installed skill without re-approving it.
    (folder / "SKILL.md").write_text(
        "---\nname: edited\ndescription: d\n---\nnow it does something else\n",
        encoding="utf-8",
    )
    reconcile(store, skills_dir)

    assert not _trusted(skills_dir, "edited"), (
        "the approval was carried onto content it was never granted for"
    )

def test_a_rebuild_keeps_an_approved_skills_trust(tmp_path: Path) -> None:
    """The scanner cannot know what was approved, so it must not overwrite it.

    ``iter_skill_artifacts`` loads every managed skill (``.fetched/``,
    ``.evolved/``) as ``untrusted`` no matter what is on disk — that is the
    fail-closed rule working. But the snapshot is written *from* the scanner, so
    a rebuild used to launder a trusted, published skill into ``untrusted`` and
    drop it out of the prompt. The registry row is the approval; the rebuild
    only gets to say where the files are.
    """
    skills_dir = tmp_path / "skills"
    published = _skill_dir(skills_dir / ".evolved", "banana")
    store = _record_store(
        _record("banana", published, source="evolved", trust="trusted")
    )

    reconcile(store, skills_dir)

    snapshot = {r.name: r.trust for r in SkillIndex(index_path(skills_dir)).list()}
    assert snapshot == {"banana": "trusted"}


def test_a_rebuild_never_promotes_an_untrusted_skill(tmp_path: Path) -> None:
    """The reverse direction, which is the security-relevant one.

    A root-level skill loads as ``trusted`` straight off disk, so a rebuild used
    to overwrite an explicit ``untrusted`` verdict with ``trusted`` — silently
    granting a skill the operator had refused. Trust must only ever be narrowed
    by a rebuild, never widened.
    """
    skills_dir = tmp_path / "skills"
    refused = _skill_dir(skills_dir, "evil")
    store = _record_store(_record("evil", refused, trust="untrusted"))

    reconcile(store, skills_dir)

    snapshot = {r.name: r.trust for r in SkillIndex(index_path(skills_dir)).list()}
    assert snapshot == {"evil": "untrusted"}


def test_a_rebuild_keeps_the_approved_digest(tmp_path: Path) -> None:
    """The digest is what an approval is bound to; a scan cannot re-decide it."""
    skills_dir = tmp_path / "skills"
    present = _skill_dir(skills_dir / ".fetched", "pdf")
    store = _record_store(
        _record("pdf", present, source="catalog", trust="trusted", digest="sha256:approved")
    )

    reconcile(store, skills_dir)

    snapshot = SkillIndex(index_path(skills_dir)).list()
    assert [record.digest for record in snapshot] == ["sha256:approved"]


def test_a_rebuild_still_refreshes_what_the_files_say(tmp_path: Path) -> None:
    """Keeping the verdicts must not freeze the descriptive fields.

    An edited summary or a new version is *supposed* to show up after a rebuild
    — only the four decided fields are pinned to the registry.
    """
    skills_dir = tmp_path / "skills"
    present = _skill_dir(skills_dir / ".fetched", "pdf")
    (present / "SKILL.md").write_text(
        "---\nname: pdf\nversion: 9.9\ndescription: rewritten summary\n---\nbody\n",
        encoding="utf-8",
    )
    store = _record_store(
        _record(
            "pdf",
            present,
            source="catalog",
            trust="trusted",
            version="1.0",
            description="stale summary",
        )
    )

    reconcile(store, skills_dir)

    snapshot = SkillIndex(index_path(skills_dir)).list()[0]
    assert snapshot.description == "rewritten summary"
    assert snapshot.version == "9.9"
    assert snapshot.trust == "trusted"


def test_an_unregistered_managed_skill_stays_untrusted(tmp_path: Path) -> None:
    """No registry row means no approval, so the scan's verdict is the only one.

    Checked under a managed directory, where the fail-closed default applies: a
    downloaded skill with no row stays untrusted. (A skill at the *root* is the
    user's own work and loads trusted by design — see ``create_skill_registry``
    and ``test_user_authored_skill_at_the_root_stays_trusted``.)
    """
    skills_dir = tmp_path / "skills"
    _skill_dir(skills_dir / ".fetched", "copied-in")
    store = _record_store()

    reconcile(store, skills_dir)

    snapshot = {r.name: r.trust for r in SkillIndex(index_path(skills_dir)).list()}
    assert snapshot == {"copied-in": "untrusted"}


# -- helpers -------------------------------------------------------------------


def _export(store: MemorySkillStore, skills_dir: Path) -> None:
    """The snapshot a completed install leaves, without touching an event loop."""
    SkillIndex(index_path(skills_dir)).save(list(store.records.values()))


def _trusted(skills_dir: Path, name: str) -> bool:
    """Does the runtime load ``name`` as trusted, reading the index as it does?"""
    registry = create_skill_registry(
        skills_dir, index=SkillIndex(index_path(skills_dir))
    )
    return registry.get(name).trust == TrustLevel.TRUSTED.value


def _record_store(*records: SkillRecord) -> MemorySkillStore:
    """Build a ``MemorySkillStore`` synchronously, without an event loop."""
    store = MemorySkillStore()
    for record in records:
        store.records[record.name] = record
    return store


def _list(store: MemorySkillStore) -> list[SkillRecord]:
    return sorted(store.records.values(), key=lambda record: record.name)

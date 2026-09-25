"""The local skill index: a JSON summary of installed skills (design §7.2).

The index is what the matcher and the L0 injection read, so it must stay small:
it stores :class:`SkillRecord` entries, never full ``instructions`` bodies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from Sprout.skills.layout import index_path
from Sprout.skills.loader import iter_skill_artifacts, skill_menu_path
from Sprout.skills.models import SkillRecord

if TYPE_CHECKING:
    from Sprout.storage.contracts.skills import SkillStore

logger = logging.getLogger("sprout.skills")

#: Bumped when the on-disk shape changes so readers can migrate or reset.
INDEX_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SkillIndex:
    """Reads and writes ``<hub>/index.json``."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    # -- read / write ----------------------------------------------------------

    def load(self) -> list[SkillRecord]:
        """Return the indexed records; a missing/unreadable file reads as empty."""
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Skill index %s is unreadable; treating as empty", self._path)
            return []
        entries = raw.get("skills", []) if isinstance(raw, dict) else []
        return [SkillRecord.from_dict(entry) for entry in entries if isinstance(entry, dict)]

    def save(self, records: list[SkillRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "generated_at": _now(),
            "skills": [record.to_dict() for record in records],
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    # -- queries ---------------------------------------------------------------

    def get(self, name: str) -> SkillRecord | None:
        for record in self.load():
            if record.name == name:
                return record
        return None

    def list(
        self,
        *,
        source: str | None = None,
        trust: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillRecord]:
        records = self.load()
        if source is not None:
            records = [r for r in records if r.source == source]
        if trust is not None:
            records = [r for r in records if r.trust == trust]
        if enabled_only:
            records = [r for r in records if r.enabled]
        return records

    # -- mutation --------------------------------------------------------------

    def upsert(self, record: SkillRecord) -> None:
        records = [r for r in self.load() if r.name != record.name]
        records.append(record)
        records.sort(key=lambda r: r.name)
        self.save(records)

    def remove(self, name: str) -> bool:
        records = self.load()
        kept = [r for r in records if r.name != name]
        if len(kept) == len(records):
            return False
        self.save(kept)
        return True

    # -- rebuild ---------------------------------------------------------------

    def rebuild(self, skills_dir: str | Path, *, stamp: str | None = None) -> list[SkillRecord]:
        """Re-scan ``skills_dir`` and rewrite the index from scratch.

        Shares :func:`~Sprout.skills.loader.load_skills` with the runtime, so the
        index and the registry always agree on what is installed — including
        skills in ``.fetched/`` / ``.evolved/``. The ``.hub`` / ``.quarantine``
        bookkeeping directories hold no ``SKILL.md`` and are never indexed.

        **This is a disk scan, and it is allowed to have an opinion.** It sees
        only what is on disk, so a skill the registry knows about whose files are
        gone simply does not come back — which is the right answer for the
        snapshot, but leaves the registry holding a row nothing on disk backs.
        Callers that own a registry should reconcile against it and report the
        divergence (see :func:`reconcile`); this method alone cannot, because it
        has no registry to compare with.

        Because of that, **this is only safe on a tree with no registry.** The
        scan loads managed skills as untrusted by design, so writing its verdict
        into a snapshot that already recorded an approval *revokes* it — every
        downloaded and evolved skill drops out of the prompt on the next run.
        Use :func:`reconcile` whenever a registry exists; this is for the
        ``--dir`` standalone tree, where nothing was ever approved.
        """
        out = scan_records(skills_dir, stamp=stamp)
        self.save(out)
        return out


def _carry_approval(disk: SkillRecord, registered: SkillRecord | None) -> SkillRecord:
    """Overlay the registry's trust decision onto a freshly scanned record.

    The scan cannot know whether a skill was approved: ``iter_skill_artifacts``
    deliberately force-loads everything under ``.fetched/`` and ``.evolved/`` as
    ``untrusted``, because a downloaded skill that could mark itself trusted
    would defeat the trust gate. That is the right answer for a *loader*, and
    the wrong answer for a snapshot — the snapshot is the authority the runtime
    restores trust *from*, so writing the loader's placeholder into it revoked
    the approval of every downloaded and evolved skill on each rebuild.

    Carrying ``(trust, digest)`` verbatim is what keeps the runtime's own check
    meaningful: ``_restore_trust`` compares the recorded digest against the
    skill on disk, so a skill edited since it was approved stops matching and
    is downgraded there — the content check stays in exactly one place.

    ``enabled`` and ``pinned`` ride along for the same reason: they are operator
    switches, not properties of the files, so a file walk cannot re-derive them
    and must not overwrite them. Everything descriptive — version, description,
    tags, and the path — is re-observed, so an edited skill's summary stays
    current.

    A record with no registry row keeps the scan's verdict. For a managed
    subdirectory that is ``untrusted`` (nothing approved it); for a
    user-authored skill at the root it is ``trusted``, which is the historical
    behaviour for skills that were never installed through the broker.
    """
    if registered is None:
        return disk
    return replace(
        disk,
        trust=registered.trust,
        digest=registered.digest,
        enabled=registered.enabled,
        pinned=registered.pinned,
    )


def scan_records(skills_dir: str | Path, *, stamp: str | None = None) -> list[SkillRecord]:
    """The on-disk records under ``skills_dir``, writing nothing.

    The read half of :meth:`SkillIndex.rebuild`, shared with :func:`reconcile`
    so "what is present" has one definition.
    """
    at = stamp or _now()
    out = [
        SkillRecord.from_skill(
            skill,
            path=str(path),
            updated_at=at,
            menu_path=skill_menu_path(path, skills_dir),
        )
        for skill, path in iter_skill_artifacts(skills_dir)
    ]
    out.sort(key=lambda r: r.name)
    return out


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    """How the registry and the on-disk tree disagree."""

    #: In the registry, but its recorded ``path`` no longer exists. The row is
    #: claiming an install that is not there; ``sprout skills list`` shows it.
    missing: tuple[SkillRecord, ...] = ()
    #: On disk and loadable, but the registry has no row for it. Nothing
    #: approved it, so the trust gate loads it as untrusted and it stays out of
    #: the prompt — visible to ``index.json``, invisible to the model.
    unregistered: tuple[SkillRecord, ...] = ()
    #: In both. The normal case.
    ok: tuple[SkillRecord, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.missing and not self.unregistered


def reconcile(
    store: SkillStore,
    skills_dir: str | Path,
    *,
    stamp: str | None = None,
) -> tuple[ReconcileReport, list[SkillRecord]]:
    """Compare the registry against disk, and write the snapshot from disk.

    The registry is the authority on what was *approved*; the tree is the
    authority on what is *present*. Neither alone is the truth, and the two can
    drift in both directions:

    - A skill file deleted by hand leaves a registry row pointing at nothing.
    - A skill folder copied in by hand has no row, so it loads untrusted.

    ``missing`` rows are **dropped from the snapshot but not from the store**: a
    failed or moved install must stay visible to ``sprout skills list`` and to
    the operator, rather than being quietly forgotten by the next rebuild. This
    returns what it wrote, so the caller can report the divergence.

    **The snapshot is disk-shaped, but the registry still owns the verdicts.**
    Writing the raw disk records here was a privilege bug in both directions:
    the scanner hard-codes ``trust`` (``untrusted`` under ``.fetched/`` /
    ``.evolved/``, ``trusted`` at the root) and so cannot know what was
    approved. A published skill silently lost its trust and fell out of the
    prompt, and — worse — an explicit ``untrusted`` verdict was overwritten with
    ``trusted``, promoting a skill the operator had refused. So a registered
    skill keeps its registry ``trust``, ``digest``, ``enabled`` and ``pinned``
    (the fields a decision was made about), while everything the scanner
    observes — how to load the skill, and where it lives — comes from disk. A
    skill with no registry row is left exactly as scanned: untrusted, and
    invisible to the model.
    """
    import asyncio

    records = asyncio.run(store.list())
    scanned = scan_records(skills_dir, stamp=stamp)
    registered = {record.name: record for record in records}
    # The scan says what is present; the registry says what was approved. The
    # snapshot has to be both, or a rebuild demotes every managed skill.
    on_disk = {
        record.name: _carry_approval(record, registered.get(record.name))
        for record in scanned
    }

    missing = tuple(record for record in records if record.name not in on_disk)
    unregistered = tuple(
        record for name, record in on_disk.items() if name not in registered
    )
    ok = tuple(record for record in records if record.name in on_disk)
    # Snapshot what is actually loadable: a row whose files are gone would
    # otherwise put a skill in the prompt that cannot be read. ``on_disk``
    # already carries the registry's verdict, applied above.
    written = sorted(on_disk.values(), key=lambda record: record.name)
    SkillIndex(index_path(skills_dir)).save(written)
    return ReconcileReport(missing=missing, unregistered=unregistered, ok=ok), written


async def export_index(store: SkillStore, path: str | Path) -> list[SkillRecord]:
    """Rewrite the JSON snapshot of ``index.json`` from the registry (design §10.4).

    The registry is the source of truth; this file is the derived view the matcher
    and the L0 injection read. Returns the records that were written.
    """
    records = await store.list()
    SkillIndex(path).save(records)
    return records

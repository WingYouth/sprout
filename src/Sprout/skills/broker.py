"""The only entry point for installing or enabling a skill (design §7.4/§8.4).

The broker decides nothing itself. It scans, builds an :class:`ActionRequest`, and
obeys whatever the layered policy engine returns — asking a human through
:class:`~Sprout.security.approval.ApprovalManager` when the policy says so. This
mirrors the rule stated in ``security/__init__.py``: brokers never decide.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Sprout.gateway.identity import Principal
from Sprout.security.access import (
    AccessDecision,
    ActionRequest,
    ActionType,
)
from Sprout.skills.index import export_index
from Sprout.skills.layout import index_path, install_target, quarantine_dir
from Sprout.skills.loader import files_digest, load_standard_skill, skill_menu_path
from Sprout.skills.models import SkillRecord
from Sprout.skills.scanner import ScanReport, SkillScanner
from Sprout.skills.sources.base import SkillBundle, SkillSource, SkillStub
from Sprout.skills.trust import Quarantine

if TYPE_CHECKING:
    from Sprout.security.approval import ApprovalManager
    from Sprout.security.layered_policy import LayeredPolicyEngine
    from Sprout.storage.contracts.skills import SkillStore


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    """What the broker decided for one candidate skill."""

    decision: AccessDecision
    reason: str = ""
    report: ScanReport | None = None
    approval_id: str = ""
    matched_rules: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.decision in {AccessDecision.ALLOW, AccessDecision.ALLOW_REDACTED}

    @property
    def needs_approval(self) -> bool:
        return self.decision is AccessDecision.REQUIRE_APPROVAL

    @property
    def rejected(self) -> bool:
        return self.decision is AccessDecision.DENY


@dataclass(frozen=True, slots=True)
class InstallReport:
    """The result of a full install attempt (design §7.4)."""

    name: str
    source: str
    outcome: InstallOutcome
    installed_path: str = ""
    quarantined_path: str = ""
    record: SkillRecord | None = None
    #: Content digest of what was fetched. Carried out so a caller that approves
    #: later can record the same digest the approval was granted against.
    digest: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.installed_path)

    @property
    def pending_approval(self) -> bool:
        return self.outcome.needs_approval

    @property
    def rejected(self) -> bool:
        return self.outcome.rejected


def approval_arguments(
    *, name: str, source: str, origin: str = "", digest: str = ""
) -> dict[str, str]:
    """The arguments a skill install is approved and consumed against.

    Both :meth:`SkillInstallBroker.request_approval` and the grant check in
    :meth:`SkillInstallBroker.evaluate` fingerprint these exact keys, so a
    realistic digest change — a repository moving between the prompt and the
    approval — re-prompts rather than installing content nobody saw.
    """
    return {
        "skill": name,
        "source": source,
        "origin": origin,
        "digest": digest,
    }


class SkillInstallBroker:
    """Scan → policy → (approval) for a skill that is about to be installed."""

    def __init__(
        self,
        policy: LayeredPolicyEngine,
        *,
        scanner: SkillScanner | None = None,
        approvals: ApprovalManager | None = None,
        skills: SkillStore | None = None,
    ) -> None:
        self._policy = policy
        self._scanner = scanner or SkillScanner()
        self._approvals = approvals
        self._skills = skills

    async def evaluate(
        self,
        *,
        name: str,
        source: str,
        origin: str = "",
        digest: str = "",
        scan: ScanReport | None = None,
        script_text: str = "",
        actor: Principal | None = None,
        task_id: str = "",
    ) -> InstallOutcome:
        """Scan and decide. Never installs anything itself.

        Async because the decision consults :meth:`ApprovalManager.is_approved`
        to consume a previously granted approval. Skipping that check made an
        approved install re-request approval forever: the policy engine grades by
        provenance and has no view of granted approvals, so ``skill.install``
        returned ``REQUIRE_APPROVAL`` on every retry (the other brokers —
        git, network, apply — all consume their grant this way).
        """
        report = scan
        if report is None:
            report = self._scanner.scan(origin) if origin else ScanReport()

        # 1) Scanner hard floor: a fatal finding never reaches the policy engine,
        #    so it cannot be approved past (design §8.4).
        if report.fatal:
            return InstallOutcome(
                AccessDecision.DENY,
                "Hard floor: scan found a fatal issue",
                report,
                matched_rules=("scan:fatal",),
            )

        # 2) Everything else belongs to the policy engine. The payload travels as
        #    ``script`` so the shared hard floor inspects it too.
        request = ActionRequest(
            task_id=task_id,
            actor=actor or Principal(user_id="system"),
            action=ActionType.SKILL_INSTALL,
            arguments={
                "skill": name,
                "source": source,
                "origin": origin,
                "digest": digest,
                "script": script_text,
                "findings": report.summary,
            },
        )
        decision = self._policy.decide(request)

        # A grant already issued for this exact install (same skill, source,
        # origin and digest — the approval fingerprint covers all four) is spent
        # here, which turns the retry that follows "approve" into an install
        # instead of another prompt.
        if decision.decision is AccessDecision.REQUIRE_APPROVAL and self._approvals is not None:
            granted = await self._approvals.is_approved(
                ActionType.SKILL_INSTALL.value,
                approval_arguments(name=name, source=source, origin=origin, digest=digest),
                task_id=task_id,
            )
            if granted:
                return InstallOutcome(
                    AccessDecision.ALLOW,
                    "Approved by a granted approval",
                    report,
                    matched_rules=("approval:granted",),
                )

        return InstallOutcome(
            decision.decision,
            decision.reason,
            report,
            decision.approval_id,
            decision.matched_rules,
        )

    async def request_approval(
        self,
        outcome: InstallOutcome,
        *,
        name: str,
        source: str,
        arguments: Mapping[str, Any] | None = None,
        task_id: str = "",
        requested_by: str = "system",
        resource_scope: str = "",
    ) -> InstallOutcome:
        """Ask a human to approve an install the policy marked ``require_approval``."""
        if self._approvals is None or not outcome.needs_approval:
            return outcome
        record = await self._approvals.request(
            ActionType.SKILL_INSTALL.value,
            dict(arguments or {"skill": name, "source": source}),
            task_id=task_id,
            requested_by=requested_by,
            single_use=True,
            resource_scope=resource_scope or f"skill:{name}",
            source=source,
        )
        return InstallOutcome(
            outcome.decision,
            outcome.reason,
            outcome.report,
            approval_id=getattr(record, "id", ""),
            matched_rules=outcome.matched_rules,
        )

    async def promote_approved(
        self,
        name: str,
        *,
        source: str,
        origin: str = "",
        digest: str = "",
        skills_dir: str | Path,
    ) -> InstallReport:
        """Move an approved quarantine entry to its final home (§7.4).

        :meth:`install` returns as soon as it has asked for approval, leaving the
        skill staged: a human decision recorded later has nothing to promote it.
        This is that second half, for callers that approve out of band — the
        ``sprout skills install`` / ``sprout approvals approve`` flow. It refuses
        when the skill is not actually staged, so it can never conjure a skill
        that failed the scanner.
        """
        root = Path(skills_dir)
        quarantine = Quarantine(quarantine_dir(root))
        staged = quarantine.path(name)
        if not staged.is_dir():
            return InstallReport(
                name=name,
                source=source,
                outcome=InstallOutcome(
                    AccessDecision.DENY,
                    f"{name} is not staged in quarantine; nothing to promote",
                    matched_rules=("quarantine:missing",),
                ),
            )

        target = install_target(root, source, name)
        if target.exists():
            suffix = (digest or "unknown").rsplit(":", 1)[-1][:8]
            target = target.with_name(f"{target.name}-{suffix}")
        # A skill staged by ``install`` may be a single-file ``.toml``; promote
        # it by the same rule, or approving an install would bury the file.
        target = _promote_staged(quarantine, name, target)
        record = await self.record_install(
            name=name,
            source=source,
            origin=origin,
            digest=digest,
            trust="trusted",
            path=str(target),
            skills_dir=root,
        )
        if self._skills is not None:
            await export_index(self._skills, index_path(root))
        return InstallReport(
            name=name,
            source=source,
            outcome=InstallOutcome(
                AccessDecision.ALLOW, "approved and promoted", matched_rules=("approval:granted",)
            ),
            installed_path=str(target),
            record=record,
        )

    async def record_install(
        self,
        *,
        name: str,
        source: str,
        origin: str = "",
        digest: str = "",
        trust: str = "untrusted",
        path: str = "",
        enabled: bool = True,
        skills_dir: str | Path | None = None,
    ) -> SkillRecord | None:
        """Register the install in the skill store (no store → no-op)."""
        if self._skills is None:
            return None
        record = _skill_record(
            name=name,
            source=source,
            origin=origin,
            digest=digest,
            trust=trust,
            path=path,
            enabled=enabled,
            stamp=datetime.now(UTC).isoformat(),
            menu_path=skill_menu_path(path, skills_dir) if skills_dir else (),
        )
        await self._skills.upsert(record)
        return record

    async def install(
        self,
        stub: SkillStub,
        source: SkillSource,
        *,
        skills_dir: str | Path,
        actor: Principal | None = None,
        task_id: str = "",
        requested_by: str = "system",
        replace: bool = False,
    ) -> InstallReport:
        """Fetch → stage → scan → decide → (approve) → promote.

        Nothing lands in the skills directory until the policy allows it; a skill
        awaiting approval stays in quarantine.

        ``replace`` overwrites an existing install of the same name instead of
        parking the new one beside it under a digest suffix. Only an explicit
        ``--force`` sets it: silently versioning on collision is right for an
        unattended install, but wrong when the user asked for a replacement.
        """
        root = Path(skills_dir)
        bundle = await source.fetch(stub)
        digest = _bundle_digest(bundle)

        quarantine = Quarantine(quarantine_dir(root))
        staged = quarantine.stage(stub.name, bundle.files)

        report = self._scanner.scan(staged)
        outcome = await self.evaluate(
            name=stub.name,
            source=stub.source,
            origin=stub.origin,
            digest=digest,
            scan=report,
            script_text=bundle.script_text,
            actor=actor,
            task_id=task_id,
        )

        if outcome.rejected:
            quarantine.discard(stub.name)
            return InstallReport(name=stub.name, source=stub.source, outcome=outcome)

        if outcome.needs_approval:
            outcome = await self.request_approval(
                outcome,
                name=stub.name,
                source=stub.source,
                arguments=approval_arguments(
                    name=stub.name, source=stub.source, origin=stub.origin, digest=digest
                ),
                task_id=task_id,
                requested_by=requested_by,
            )
            return InstallReport(
                name=stub.name,
                source=stub.source,
                outcome=outcome,
                quarantined_path=str(staged),
                digest=digest,
            )

        target = install_target(root, stub.source, stub.name)
        if replace:
            _remove_existing(root, stub.name, target)
        elif target.exists():
            suffix = digest.rsplit(":", 1)[-1][:8]
            target = target.with_name(f"{target.name}-{suffix}")
        target = _promote(quarantine, stub.name, bundle.files, target)
        record = await self.record_install(
            name=stub.name,
            source=stub.source,
            origin=stub.origin,
            digest=digest,
            trust="trusted",
            path=str(target),
            skills_dir=root,
        )
        if self._skills is not None:
            # index.json is a derived view of the registry (§10.4)
            await export_index(self._skills, index_path(root))
        return InstallReport(
            name=stub.name,
            source=stub.source,
            outcome=outcome,
            installed_path=str(target),
            record=record,
        )


def _skill_record(
    *,
    name: str,
    source: str,
    origin: str,
    digest: str,
    trust: str,
    path: str,
    enabled: bool,
    stamp: str,
    menu_path: tuple[str, ...] = (),
) -> SkillRecord:
    """Build the registry entry for a just-installed skill, enriched from disk."""
    base = SkillRecord(
        name=name,
        version="",
        source=source,
        origin=origin,
        digest=digest,
        trust=trust,
        enabled=enabled,
        path=path,
        updated_at=stamp,
        menu_path=menu_path,
    )
    skill_md = Path(path) / "SKILL.md"
    if not path or not skill_md.is_file():
        return base
    try:
        skill = load_standard_skill(skill_md)
    except (ValueError, OSError):
        return base
    return replace(
        SkillRecord.from_skill(skill, path=path, updated_at=stamp),
        source=source,
        origin=origin or skill.origin,
        digest=digest,
        trust=trust,
        enabled=enabled,
    )


def _bundle_digest(bundle: SkillBundle) -> str:
    """Content hash over the bundle, stable across file order."""
    return files_digest(bundle.files)


def _promote(
    quarantine: Quarantine, name: str, files: Mapping[str, bytes], target: Path
) -> Path:
    """Promote a staged bundle to ``target``, honouring the single-file shape.

    A bundle holding exactly one ``.toml`` file is a single-file skill, and the
    convention for those is ``<root>/<name>.toml`` (``SkillRepository``): moving
    the staging directory would bury it at ``<root>/<name>/<name>.toml``, which
    the loader never scans. Everything else — a ``SKILL.md`` directory, or a
    multi-file bundle — keeps the directory layout.
    """
    if _is_single_toml(files):
        relative = next(iter(files))
        # ``target.name`` rather than ``name``: a collision suffix appended by
        # the caller must survive, or two versions would land on one path.
        return quarantine.promote_file(name, relative, target.with_name(f"{target.name}.toml"))
    return quarantine.promote(name, target)


def _is_single_toml(files: Mapping[str, bytes]) -> bool:
    """True for a one-file ``.toml`` bundle (the single-file skill shape)."""
    return len(files) == 1 and next(iter(files)).lower().endswith(".toml")


def _remove_existing(root: Path, name: str, target: Path) -> None:
    """Delete a previous install of ``name``, whichever shape it is in.

    A skill is either a directory ``<root>/<name>/`` or a single file
    ``<root>/<name>.toml``, and a re-import can swap one for the other. Leaving
    the other behind would be worse than untidy: the loader scans both shapes, so
    a stale ``<root>/<name>.toml`` beside a fresh ``<root>/<name>/`` makes it
    load the same name twice, one of them the old content.

    Both paths are derived from ``name``, never from a neighbouring filename.
    An earlier version used ``target.with_suffix(".toml")``, which *replaces* the
    suffix rather than appending it — for a skill named ``pdf.v1`` that resolved
    to ``<root>/pdf.toml`` and deleted an unrelated ``pdf`` skill's file, with no
    warning. Every path is checked to sit directly under ``root`` first.
    """
    resolved_root = root.resolve()
    for candidate in (target, root / f"{name}.toml", root / name):
        if candidate.resolve().parent != resolved_root:
            continue
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)
        elif candidate.is_file():
            candidate.unlink(missing_ok=True)


def _promote_staged(quarantine: Quarantine, name: str, target: Path) -> Path:
    """Promote an already-staged skill, inferring the shape from the staging dir.

    :meth:`SkillInstallBroker.promote_approved` runs after the fact, so it has
    the staged directory but not the original bundle. Re-reading the staging
    listing recovers the same decision :func:`_promote` made at install time.
    """
    staged = quarantine.path(name)
    entries = [entry for entry in staged.rglob("*") if entry.is_file()]
    if len(entries) == 1 and entries[0].suffix.lower() == ".toml":
        relative = entries[0].relative_to(staged).as_posix()
        return quarantine.promote_file(name, relative, target.with_name(f"{target.name}.toml"))
    return quarantine.promote(name, target)

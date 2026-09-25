"""Tamper-evident security audit stream (AUTHZ §7).

``~/.sprout/data/audit/security.jsonl`` records one JSON object per line, chained with
``hash = sha256(prev_hash + canonical(entry))``. Editing, reordering, or
dropping a line breaks the chain, and ``sprout audit verify`` reports exactly
where. This is separate from ``~/.sprout/data/sprout_trajectory/<task_id>.jsonl``: trajectory is
task narrative, this is the authorization record.

Write failures are **not** swallowed (that was defect C12): they increment
``failures``, go to stderr, and land in a ``.fallback`` file next to the stream
so a full disk or a held lock cannot silently erase the evidence. The caller's
response is still never blocked by auditing.

Several processes append to the same stream — ``sprout serve``, the runtime and
the CLI each build their own log — so the chain is continued under an
inter-process file lock and the tail is re-read every time. A cached tail would
fork the chain the moment another writer landed an entry (defect C13).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from Sprout.events import (
    AUDIT_APPROVAL_DECISION,
    AUDIT_APPROVAL_RESUME_FAILED,
    AUDIT_COMMAND_ALLOWLISTED,
    AUDIT_NETWORK_BLOCKED,
    AUDIT_POLICY_DECISION,
    AUTH_ROLES_DISCARDED,
    AUTH_SCOPE_EXPIRED,
    AUTH_SELF_ATTESTATION_IGNORED,
)

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings
    from Sprout.security.access import ActionRequest, PolicyDecision

GENESIS_HASH = "0" * 64

#: How long an append waits for the inter-process lock before it degrades.
#:
#: The lock is held for a sub-millisecond read-then-append, so even a burst of
#: writers clears in milliseconds. A wait longer than this means a writer is
#: stuck (paused in a debugger, a stalled disk), and the right move is to
#: degrade into ``.fallback`` rather than stall the caller — the caller is
#: often an event loop (``Runtime`` is async throughout).
LOCK_TIMEOUT_SECONDS = 0.5

#: Poll interval while waiting for the lock.
LOCK_POLL_SECONDS = 0.05

#: A tail inspection reads at most this many bytes; a full scan is the fallback.
TAIL_BLOCK_BYTES = 64 * 1024

#: Decision kinds emitted by the runtime.
KIND_POLICY_DECISION = AUDIT_POLICY_DECISION
KIND_APPROVAL_DECISION = AUDIT_APPROVAL_DECISION
KIND_APPROVAL_RESUME_FAILED = AUDIT_APPROVAL_RESUME_FAILED
KIND_COMMAND_ALLOWLISTED = AUDIT_COMMAND_ALLOWLISTED
KIND_ROLES_DISCARDED = AUTH_ROLES_DISCARDED
KIND_SCOPE_EXPIRED = AUTH_SCOPE_EXPIRED
KIND_SELF_ATTESTATION = AUTH_SELF_ATTESTATION_IGNORED
KIND_NETWORK_BLOCKED = AUDIT_NETWORK_BLOCKED


class AuditStreamUnreadable(RuntimeError):
    """The stream holds entries, but its tail cannot be read or parsed.

    Raised instead of guessing: continuing from the genesis hash would silently
    start a second branch, which looks exactly like tampering to ``verify``.
    """


@dataclass(frozen=True, slots=True)
class AuditVerification:
    """Result of walking the hash chain."""

    ok: bool
    checked: int = 0
    broken_at: int | None = None
    reason: str = ""
    #: Lines that are not chained entries at all — parseable JSON that carries
    #: neither ``kind`` nor ``hash``. They neither break the chain nor belong to
    #: it, so they are reported apart from a real break instead of being blamed
    #: for one. Left in place rather than skipped: a file-based stream has no way
    #: to know who put them there, and removing evidence is not this function's
    #: call to make.
    foreign: tuple[int, ...] = ()


def is_chained_entry(candidate: Any) -> bool:
    """Does ``candidate`` claim to be a link in the chain?

    A chained entry carries a ``kind`` (what it records) and a ``hash`` (its
    link). A line with neither is some other JSON object that landed in the
    file; a line with only one of them is a malformed entry and must still be
    treated as a break, because it does claim membership.
    """
    if not isinstance(candidate, Mapping):
        return False
    return "kind" in candidate or "hash" in candidate


def _is_fully_chained(candidate: Any) -> bool:
    """True for a complete link: it carries both ``kind`` and a usable ``hash``.

    The distinction from :func:`is_chained_entry` is what separates "skip this
    and keep going" from "stop": a foreign line has neither key, while a line
    with one of them is a damaged entry that must not be stepped over.
    """
    if not isinstance(candidate, Mapping):
        return False
    return "kind" in candidate and isinstance(candidate.get("hash"), str)


def canonical_entry(entry: Mapping[str, Any]) -> str:
    """Canonical JSON for hashing: sorted keys, no whitespace, stable across runs."""
    body = {key: value for key, value in entry.items() if key != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, entry: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(prev_hash.encode("utf-8"))
    digest.update(canonical_entry(entry).encode("utf-8"))
    return digest.hexdigest()


def _acquire_lock(handle: Any, timeout: float) -> None:
    """Take an exclusive, OS-enforced lock on ``handle``, or give up after ``timeout``."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("audit stream lock is held by another writer") from None
            time.sleep(LOCK_POLL_SECONDS)


def _release_lock(handle: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@dataclass
class SecurityAuditLog:
    """Append-only, hash-chained audit stream."""

    path: Path
    enabled: bool = True
    record_allows: bool = True
    failures: int = 0
    last_error: str = ""
    #: Synchronous hook fired when a write degrades. ``SecurityAuditLog`` must
    #: never await (it degrades inside the caller's path), so the async
    #: ``audit.write_failed`` event is scheduled from here — see
    #: :mod:`Sprout.security.audit_emit`.
    on_failure: Callable[[str, str, Mapping[str, Any]], None] | None = None
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    @classmethod
    def from_settings(cls, security: SecuritySettings) -> SecurityAuditLog:
        audit = security.audit
        return cls(Path(audit.path), enabled=audit.enabled, record_allows=audit.record_allows)

    @property
    def fallback_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".fallback")

    @property
    def lock_path(self) -> Path:
        """Sidecar the inter-process append lock is taken on."""
        return self.path.with_suffix(self.path.suffix + ".lock")

    @property
    def prev_hash(self) -> str:
        return self._tail_hash()

    # -- writing -----------------------------------------------------------
    def record(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Append one event; auditing never raises into the caller's path."""
        if not self.enabled:
            return
        try:
            self._append(kind, payload)
        except Exception as exc:  # noqa: BLE001 - audit must degrade, not break
            self._degrade(exc, kind, payload)

    def record_decision(self, request: ActionRequest, decision: PolicyDecision) -> None:
        """Record a policy decision with its actor, resource, and matched rules."""
        if not self.record_allows and decision.decision.value == "allow":
            return
        resource = request.resource
        self.record(
            KIND_POLICY_DECISION,
            {
                "actor": request.actor.user_id,
                "roles": list(request.actor.roles),
                "task_id": request.task_id,
                "action": request.action.value,
                "resource": resource.path if resource is not None else "",
                "resource_kind": resource.kind.value if resource is not None else "",
                "decision": decision.decision.value,
                "reason": decision.reason,
                "matched_rules": list(decision.matched_rules),
            },
        )

    def _append(self, kind: str, payload: Mapping[str, Any]) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind,
        }
        entry.update({str(key): value for key, value in payload.items()})
        with self._lock, self._append_guard():
            prev = self._tail_hash()
            entry["prev_hash"] = prev
            entry["hash"] = chain_hash(prev, entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def _append_guard(self) -> Iterator[None]:
        """Hold an OS lock across "read the tail, then append".

        ``self._lock`` only serialises writers inside one process; the stream is
        shared by several, so the read-then-write pair needs a lock the OS
        enforces. Waiting is bounded on purpose: when the lock cannot be had the
        append raises, and :meth:`record` degrades it into the ``.fallback``
        file rather than writing an entry that would break the chain — and
        rather than parking an async caller on a stuck peer.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        try:
            _acquire_lock(handle, LOCK_TIMEOUT_SECONDS)
            try:
                yield
            finally:
                _release_lock(handle)
        finally:
            handle.close()

    def _tail_hash(self) -> str:
        """Hash of the last *chained* entry, read from disk rather than cached.

        The fast path reads only the tail block; a stream whose last line is
        unparsable falls back to a full scan, and one that still yields no
        chained entry raises so the caller degrades instead of forking the chain
        from genesis.

        The scan walks back past lines that are not chained entries rather than
        stopping at the first one. ``read_entries`` classifies those as foreign
        — valid JSON written by something else, which ``verify_chain`` skips so
        the chain around them still validates. Stopping at one made every
        subsequent append raise ``AuditStreamUnreadable``, so a single foreign
        line silently disabled audit writing for the rest of the stream's life:
        every later event went to the ``.fallback`` sidecar instead of the chain,
        and the tamper-evident record stopped growing.
        """
        chunk = self._tail_bytes()
        if chunk:
            last = _parse_last_non_empty(chunk)
            if isinstance(last, dict) and isinstance(last.get("hash"), str):
                return last["hash"]

        entries = self.read_entries(self.path)
        for entry in reversed(entries):
            if _is_fully_chained(entry):
                return str(entry["hash"])
            if is_chained_entry(entry):
                # Claims membership (has ``kind`` or ``hash``) but is missing the
                # other half: a malformed entry, not a foreign line. Refuse
                # rather than continue from an earlier hash, which would leave
                # the malformed line silently inside a chain that still verifies.
                raise AuditStreamUnreadable(
                    f"{self.path} has a malformed entry at the tail"
                )
            # Foreign line (neither key): not part of the chain, keep walking
            # back to the last real entry.
        if any(is_chained_entry(entry) for entry in entries):
            raise AuditStreamUnreadable(
                f"{self.path} has chained entries but no readable tail"
            )
        return GENESIS_HASH

    def _tail_bytes(self) -> bytes:
        try:
            with self.path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                if size == 0:
                    return b""
                block = min(size, TAIL_BLOCK_BYTES)
                handle.seek(size - block)
                chunk = handle.read(block)
        except FileNotFoundError:
            return b""
        except OSError as exc:
            raise AuditStreamUnreadable(str(exc)) from exc
        return chunk if isinstance(chunk, bytes) else b""

    def _degrade(self, exc: Exception, kind: str, payload: Mapping[str, Any]) -> None:
        self.failures += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        sys.stderr.write(f"[sprout] audit write failed ({self.last_error}); event={kind}\n")
        sys.stderr.flush()
        hook = self.on_failure
        if hook is not None:
            try:
                hook(self.last_error, kind, payload)
            except Exception:  # noqa: BLE001 - a broken hook must not break the caller
                pass
        try:
            self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with self.fallback_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        {"ts": datetime.now(UTC).isoformat(), "kind": kind, **payload},
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001 - the last resort is stderr above
            pass

    # -- reading -----------------------------------------------------------
    @staticmethod
    def read_entries(path: str | Path) -> list[dict[str, Any]]:
        target = Path(path)
        if not target.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                entries.append({"kind": "corrupt", "raw": stripped})
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    def entries(self) -> list[dict[str, Any]]:
        return self.read_entries(self.path)

    def last_entry(self) -> dict[str, Any] | None:
        entries = self.entries()
        return entries[-1] if entries else None

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.entries()[-limit:]

    def verify(self) -> AuditVerification:
        return verify_chain(self.path)

    def report(self) -> dict[str, Any]:
        return audit_report(self.entries())


def _parse_last_non_empty(chunk: bytes) -> Any:
    """Parse the last non-empty line of a byte chunk, or return ``None``."""
    for raw in reversed(chunk.splitlines()):
        text = raw.strip()
        if not text:
            continue
        try:
            return json.loads(text.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    return None


def verify_chain(path: str | Path) -> AuditVerification:
    """Walk the chain; stop at the first line whose hash or link does not match.

    Lines that are not chained entries (:func:`is_chained_entry`) are collected
    into ``foreign`` and the walk carries on past them. They are not part of the
    chain, so they cannot have broken it — reporting them as a broken link at
    their index points the reader at the wrong culprit and hides whether the
    entries around them are intact. ``ok`` still fails whenever *any* line is not
    an entry, because a stream that cannot account for a line is not fully
    verified either; the difference is that the report now says which of the two
    happened.
    """
    entries = SecurityAuditLog.read_entries(path)
    foreign: list[int] = []
    prev = GENESIS_HASH
    checked = 0
    for index, entry in enumerate(entries):
        if entry.get("kind") == "corrupt":
            return AuditVerification(False, checked, index, "Unparsable audit line", tuple(foreign))
        if not is_chained_entry(entry):
            foreign.append(index)
            continue
        if entry.get("prev_hash") != prev:
            return AuditVerification(
                False, checked, index, "Broken hash link (prev_hash mismatch)", tuple(foreign)
            )
        expected = chain_hash(prev, entry)
        if entry.get("hash") != expected:
            return AuditVerification(
                False, checked, index, "Entry hash mismatch (line was edited)", tuple(foreign)
            )
        prev = str(entry.get("hash"))
        checked += 1
    if foreign:
        return AuditVerification(
            False,
            checked,
            None,
            f"{len(foreign)} line(s) in the stream are not audit entries",
            tuple(foreign),
        )
    return AuditVerification(True, checked, None, "")


def audit_report(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate a stream into the monthly view ``sprout audit report`` prints."""
    by_actor: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    matched: dict[str, int] = {}
    denials = 0
    for entry in entries:
        kind = str(entry.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        actor = entry.get("actor")
        if isinstance(actor, str) and actor:
            by_actor[actor] = by_actor.get(actor, 0) + 1
        action = entry.get("action")
        if isinstance(action, str) and action:
            by_action[action] = by_action.get(action, 0) + 1
        decision = entry.get("decision")
        if isinstance(decision, str) and decision:
            by_decision[decision] = by_decision.get(decision, 0) + 1
            if decision == "deny":
                denials += 1
        for rule in entry.get("matched_rules") or ():
            matched[str(rule)] = matched.get(str(rule), 0) + 1
    return {
        "total": len(entries),
        "denials": denials,
        "by_kind": _sorted_counts(by_kind),
        "by_actor": _sorted_counts(by_actor),
        "by_action": _sorted_counts(by_action),
        "by_decision": _sorted_counts(by_decision),
        "matched_rules": _sorted_counts(matched),
    }


def _sorted_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

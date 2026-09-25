"""The hard floor: operations no configuration may ever widen (AUTHZ §1.3).

The floor is evaluated *before* every policy layer. Because a layered decision
can only tighten (see :meth:`LayeredPolicyEngine._intersect`), a floor ``DENY``
can never be turned back into an allow by organization, workspace, delegation,
or risk settings. ``[security.floor] enabled`` is read-only for display: the
floor is always on, the key only exists so operators can see it in ``sprout
info``.

The command list mirrors Hermes' ``UNRECOVERABLE_BLOCKLIST``; the ``secret.read``
rule was promoted out of the default matrix so it cannot be relaxed either. Two
SQLite rules cover *statement* text, which the database broker now carries in
``arguments["sql"]`` (audit R8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from Sprout.security.access import (
    AccessDecision,
    ActionRequest,
    ActionType,
    PolicyDecision,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class FloorRule:
    """One unrecoverable-operation signature."""

    id: str
    pattern: str
    reason: str


# Arguments whose text is scanned for unrecoverable command signatures. ``sql``
# belongs here because a database statement is a command in every sense that
# matters: ``ATTACH DATABASE 'x'`` reaches files the policy never approved.
_COMMAND_ARGUMENTS = ("command", "cmd", "argv", "script", "sql")

# Mirrors Hermes' docker/security blocklist. Anchored where a false positive
# would be worse than a miss (e.g. ``reboot`` only counts as argv[0]).
DEFAULT_FLOOR_RULES: tuple[FloorRule, ...] = (
    FloorRule(
        "rm-root",
        r"\brm\s+(?:-[^\s]+\s+)*/(?:\*)?(?=\s|$)",
        "Recursive delete of the filesystem root is unrecoverable",
    ),
    FloorRule(
        "fork-bomb",
        r":\s*\(\s*\)\s*\{[^}]*\}\s*;\s*:",
        "Fork bomb",
    ),
    FloorRule(
        "mkfs",
        r"\bmkfs(?:\.[a-z0-9]+)?\b",
        "Formatting a filesystem is unrecoverable",
    ),
    FloorRule(
        "dd-to-device",
        r"\bdd\b[^|;&]*\bof=/dev/(?:sd|nvme|hd|vd|mmcblk|disk)",
        "Writing a raw disk device is unrecoverable",
    ),
    FloorRule(
        "redirect-to-device",
        r">\s*/dev/(?:sd|nvme|hd|vd|mmcblk|disk)",
        "Redirecting output onto a raw disk device is unrecoverable",
    ),
    FloorRule(
        "pipe-to-shell",
        r"\b(?:curl|wget|fetch)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b",
        "Piping a downloaded payload into a shell is unrecoverable",
    ),
    FloorRule(
        "chmod-root",
        r"\bchmod\s+(?:-R\s+)?(?:777|a\+rwx)\s+/(?:\s|$)",
        "Making the filesystem root world-writable is unrecoverable",
    ),
    FloorRule(
        "windows-format",
        r"\bformat\s+[a-z]:|\brd\s+/s\s+/q\s+[a-z]:\\|\bdel\s+/f\s+/s\s+/q\s+[a-z]:\\",
        "Formatting a Windows volume is unrecoverable",
    ),
    FloorRule(
        "host-power",
        r"^\s*(?:sudo\s+)?(?:shutdown|poweroff|halt|reboot)\b",
        "Powering the host off is unrecoverable",
    ),
    # SQLite escape primitives. Measured on this host (sqlite3 3.50.4, audit R8):
    # ``ATTACH DATABASE '<abs path>'`` succeeds and creates the file, while
    # ``SELECT load_extension(...)`` is refused by SQLite itself (``not
    # authorized``) unless the C API is explicitly enabled. The attach rule
    # closes the reachable hole; the load_extension rule is the guard for the
    # day someone enables that API, because the floor is the only layer that
    # cannot be widened afterwards.
    FloorRule(
        "sqlite-attach",
        r"\battach\s+(?:database\s+)?(?:'|\")",
        "Attaching another database file reaches files no policy approved",
    ),
    FloorRule(
        "sqlite-load-extension",
        r"\bload_extension\s*\(",
        "Loading a native SQLite extension executes arbitrary code",
    ),
    FloorRule(
        "skill-unconstrained-shell",
        r"\bsubprocess\.(?:run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True",
        "A skill that runs unconstrained shell commands is unrecoverable",
    ),
)


class HardFloor:
    """Checks a request against the unrecoverable-operation blocklist."""

    def __init__(self, rules: Sequence[FloorRule] = DEFAULT_FLOOR_RULES) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[FloorRule, ...]:
        return self._rules

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.id for rule in self._rules)

    def check(self, request: ActionRequest) -> PolicyDecision | None:
        """Return a ``DENY`` decision when the request hits the floor, else ``None``."""
        if request.action is ActionType.SECRET_READ:
            return self._deny("secret-read", "Secret values are never readable")

        for subject in self._subjects(request):
            for rule in self._rules:
                if re.search(rule.pattern, subject, flags=re.IGNORECASE):
                    return self._deny(rule.id, rule.reason)
        return None

    @staticmethod
    def _deny(rule_id: str, reason: str) -> PolicyDecision:
        return PolicyDecision(
            decision=AccessDecision.DENY,
            reason=f"Hard floor: {reason}",
            matched_rules=(f"floor:{rule_id}",),
        )

    @staticmethod
    def _subjects(request: ActionRequest) -> tuple[str, ...]:
        subjects: list[str] = []
        for key in _COMMAND_ARGUMENTS:
            value = request.arguments.get(key)
            if isinstance(value, str):
                subjects.append(value)
            elif isinstance(value, (list, tuple)):
                subjects.append(" ".join(str(part) for part in value))
        if request.resource is not None and request.resource.path:
            subjects.append(request.resource.path)
        return tuple(subjects)

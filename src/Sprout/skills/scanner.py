"""Deterministic static checks for a skill before it may be trusted (design §8.1).

The scanner never executes skill content and never calls a model: it is a fixed
set of pattern checks, so the same input always yields the same report. Findings
are graded ``info`` < ``warning`` < ``fatal``; a single ``fatal`` finding blocks
installation outright — that is the hard floor of §8.4, enforced *before* the
policy engine and therefore impossible to approve past.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Bumped whenever the rule set changes. Recorded in the trust ledger so a scan
#: from an older rule set can be recognised as stale and re-run.
SCANNER_VERSION = 1

#: Extensions whose text is inspected; ``SKILL.md`` is always included.
_TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".py", ".sh", ".bash", ".ps1", ".js", ".ts"}
)

#: Files larger than this are counted but not content-scanned.
MAX_SCAN_BYTES = 1_000_000

FATAL = "fatal"
WARNING = "warning"
INFO = "info"

#: ``(rule id, severity, compiled pattern, human detail)``.
_RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (
        "credential-leak",
        FATAL,
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "Embedded private key",
    ),
    (
        "credential-leak",
        FATAL,
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "Embedded AWS access key id",
    ),
    (
        "credential-leak",
        FATAL,
        re.compile(r"\b(?:sk|pk)-[A-Za-z0-9]{20,}\b"),
        "Embedded API key",
    ),
    (
        "unicode-smuggling",
        FATAL,
        re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]"),
        "Zero-width or bidirectional control characters",
    ),
    (
        "unrecoverable-command",
        FATAL,
        re.compile(r"\brm\s+(?:-[^\s]+\s+)*/(?:\*)?(?=\s|$)"),
        "Recursive delete of the filesystem root",
    ),
    (
        "unrecoverable-command",
        FATAL,
        re.compile(r"\b(?:curl|wget|fetch)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b"),
        "Piping a downloaded payload into a shell",
    ),
    (
        "unconstrained-shell",
        FATAL,
        re.compile(r"\bsubprocess\.(?:run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True"),
        "Runs shell commands without constraints",
    ),
    (
        "prompt-injection",
        WARNING,
        re.compile(
            r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b",
            re.IGNORECASE,
        ),
        "Text tries to override prior instructions",
    ),
    (
        "exfiltration",
        WARNING,
        re.compile(
            r"\b(?:requests\.post|fetch|curl)\b[^;\n]{0,80}\$\{?(?:API_KEY|TOKEN|SECRET|PASSWORD)"
        ),
        "Sends a credential to the network",
    ),
)


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """One rule hit, with the file that produced it."""

    rule: str
    severity: str
    detail: str
    path: str = ""


@dataclass(frozen=True, slots=True)
class ScanReport:
    """The outcome of scanning one skill artifact."""

    findings: tuple[ScanFinding, ...] = ()
    files_scanned: int = 0

    @property
    def fatal(self) -> bool:
        """True when installation must be refused outright (§8.4 hard floor)."""
        return any(finding.severity == FATAL for finding in self.findings)

    @property
    def warnings(self) -> tuple[ScanFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == WARNING)

    @property
    def summary(self) -> str:
        if not self.findings:
            return "no findings"
        return "; ".join(f"{finding.severity}:{finding.rule}" for finding in self.findings)


class SkillScanner:
    """Scans a skill directory or a single file without executing anything."""

    def __init__(self, *, max_bytes: int = MAX_SCAN_BYTES) -> None:
        self._max_bytes = max_bytes

    def scan(self, target: str | Path) -> ScanReport:
        findings: list[ScanFinding] = []
        scanned = 0
        for path in self._iter_files(Path(target)):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if len(raw) > self._max_bytes:
                findings.append(
                    ScanFinding("oversized-file", WARNING, f"{len(raw)} bytes", str(path))
                )
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            for rule_id, severity, pattern, detail in _RULES:
                if pattern.search(text):
                    findings.append(ScanFinding(rule_id, severity, detail, str(path)))
        return ScanReport(findings=tuple(findings), files_scanned=scanned)

    @staticmethod
    def _iter_files(root: Path) -> list[Path]:
        if root.is_file():
            return [root]
        if not root.is_dir():
            return []
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
            and (path.suffix.lower() in _TEXT_SUFFIXES or path.name == "SKILL.md")
        )

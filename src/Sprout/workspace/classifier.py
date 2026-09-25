"""Explicit resource classification (AUTHZ §3.1).

Classification used to be implicit in whichever scanner happened to run first,
so "what kind is ``.env``?" had no single authoritative answer. It is now a
rule table:

===========================================================  ===================
pattern (glob, matched against the workspace-relative path)   kind
===========================================================  ===================
``.env*``, ``*.pem``, ``*.key``, ``secrets/**``, ``**/.ssh/**``  SECRET
``data/**``, ``~/.sprout/data/**``, ``*.db``, ``*.sqlite*``      DATA
``**/credentials*``, ``**/token*``, private directories         SENSITIVE
``tests/**``, ``**/*_test.py``                                  TEST
``*.md``                                                        DOCUMENTATION
outside the workspace, or a device-namespace path                EXTERNAL
everything else                                                 SOURCE / PUBLIC
===========================================================  ===================

Device-namespace paths are rejected before any resolution (see
:func:`is_device_namespace`); operators override any pattern through
``[security.classify]``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from Sprout.workspace.models import ResourceKind

#: Windows NT / device-namespace prefixes. They are rejected on the **raw
#: string**, before any resolution: merely resolving ``\??\UNC\host\share``
#: triggers outbound SMB authentication and can leak the operator's NTLM hash,
#: so the check has to happen before ``Path.resolve()`` ever sees the input.
#: Mirrors Hermes' device-namespace rejection list.
_DEVICE_PREFIXES: tuple[str, ...] = ("\\??\\", "\\\\.\\")

#: Prefix whose body decides: ``\\?\C:\...`` (extended-length local path) is
#: harmless, while ``\\?\UNC\...`` and ``\\?\GLOBALROOT`` are not.
_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_REJECT_BODIES: tuple[str, ...] = ("unc\\", "globalroot")


def is_device_namespace(path: str | Path) -> bool:
    """True for Windows NT / device-namespace paths that must never be resolved.

    Ordinary extended-length local paths (``\\\\?\\C:\\...``) and plain UNC
    shares (``\\\\server\\share``) return ``False`` — they are unaffected.
    """
    text = str(path).strip()
    if not text:
        return False
    folded = text.casefold()
    if any(folded.startswith(prefix) for prefix in _DEVICE_PREFIXES):
        return True
    if folded.startswith(_EXTENDED_PREFIX):
        body = folded[len(_EXTENDED_PREFIX) :]
        return any(body.startswith(entry) for entry in _EXTENDED_REJECT_BODIES)
    return False


@dataclass(frozen=True, slots=True)
class ClassifyRule:
    """One ``pattern -> kind`` entry; the first matching rule wins."""

    id: str
    pattern: str
    kind: ResourceKind


DEFAULT_CLASSIFY_RULES: tuple[ClassifyRule, ...] = (
    ClassifyRule("secret-env", ".env*", ResourceKind.SECRET),
    ClassifyRule("secret-env-nested", "**/.env*", ResourceKind.SECRET),
    ClassifyRule("secret-key-suffix", "*.pem", ResourceKind.SECRET),
    ClassifyRule("secret-key-suffix", "*.key", ResourceKind.SECRET),
    ClassifyRule("secret-key-suffix", "*.p12", ResourceKind.SECRET),
    ClassifyRule("secret-key-suffix", "*.pfx", ResourceKind.SECRET),
    ClassifyRule("secret-ssh-dir", ".ssh/**", ResourceKind.SECRET),
    ClassifyRule("secret-ssh-dir", "**/.ssh/**", ResourceKind.SECRET),
    ClassifyRule("secret-dir", "secrets/**", ResourceKind.SECRET),
    ClassifyRule("secret-dir", "**/secrets/**", ResourceKind.SECRET),
    ClassifyRule("secret-identity", "id_rsa", ResourceKind.SECRET),
    ClassifyRule("secret-identity", "id_ed25519", ResourceKind.SECRET),
    ClassifyRule("sensitive-name", "credentials*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-name", "**/credentials*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-token", "token*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-token", "**/token*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-secret", "secret*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-rc", ".npmrc", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-rc", ".pypirc", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-rc", ".netrc", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-account", "service-account.json", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-prod", "*.prod.*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-prod", "*.production*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-prod", "prod.config*", ResourceKind.SENSITIVE),
    ClassifyRule("sensitive-data", "customers*", ResourceKind.SENSITIVE),
    ClassifyRule("sprout-data-dir", ".sprout/data/**", ResourceKind.DATA),
    ClassifyRule("data-dir", "data/**", ResourceKind.DATA),
    ClassifyRule("data-db", "*.db", ResourceKind.DATA),
    ClassifyRule("data-db", "*.db-*", ResourceKind.DATA),
    ClassifyRule("data-db", "*.sqlite", ResourceKind.DATA),
    ClassifyRule("data-db", "*.sqlite3", ResourceKind.DATA),
    ClassifyRule("public-readme", "readme*", ResourceKind.PUBLIC),
    ClassifyRule("public-license", "license*", ResourceKind.PUBLIC),
    ClassifyRule("public-notice", "notice*", ResourceKind.PUBLIC),
    ClassifyRule("public-changelog", "changelog*", ResourceKind.PUBLIC),
    ClassifyRule("public-contributing", "contributing*", ResourceKind.PUBLIC),
    ClassifyRule("public-conduct", "code_of_conduct*", ResourceKind.PUBLIC),
    ClassifyRule("test-dir", "tests/**", ResourceKind.TEST),
    ClassifyRule("test-dir", "test/**", ResourceKind.TEST),
    ClassifyRule("test-dir", "**/__tests__/**", ResourceKind.TEST),
    ClassifyRule("test-name", "test_*.py", ResourceKind.TEST),
    ClassifyRule("test-name", "*_test.py", ResourceKind.TEST),
    ClassifyRule("test-name", "*.test.ts", ResourceKind.TEST),
    ClassifyRule("test-name", "*.test.tsx", ResourceKind.TEST),
    ClassifyRule("test-name", "*.spec.ts", ResourceKind.TEST),
    ClassifyRule("config-file", "dockerfile", ResourceKind.CONFIG),
    ClassifyRule("config-file", "makefile", ResourceKind.CONFIG),
    ClassifyRule("config-file", "pyproject.toml", ResourceKind.CONFIG),
    ClassifyRule("config-file", "package.json", ResourceKind.CONFIG),
    ClassifyRule("config-file", "go.mod", ResourceKind.CONFIG),
    ClassifyRule("config-file", "cargo.toml", ResourceKind.CONFIG),
    ClassifyRule("config-file", "pom.xml", ResourceKind.CONFIG),
    ClassifyRule("config-dir", "config/**", ResourceKind.CONFIG),
    ClassifyRule("config-dir", ".github/**", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.toml", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.yaml", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.yml", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.json", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.ini", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.cfg", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.xml", ResourceKind.CONFIG),
    ClassifyRule("config-suffix", "*.csv", ResourceKind.CONFIG),
    ClassifyRule("documentation-suffix", "*.md", ResourceKind.DOCUMENTATION),
    ClassifyRule("documentation-suffix", "*.rst", ResourceKind.DOCUMENTATION),
    ClassifyRule("documentation-suffix", "*.txt", ResourceKind.DOCUMENTATION),
    ClassifyRule("documentation-dir", "docs/**", ResourceKind.DOCUMENTATION),
    ClassifyRule("binary-suffix", "*.png", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.jpg", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.jpeg", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.gif", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.pdf", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.zip", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.tar", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.gz", ResourceKind.BINARY),
    ClassifyRule("binary-suffix", "*.pyc", ResourceKind.BINARY),
    ClassifyRule("source-suffix", "*.py", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.pyi", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.ts", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.tsx", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.js", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.jsx", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.go", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.rs", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.java", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.kt", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.tf", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.sql", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.sh", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.css", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.html", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.scss", ResourceKind.SOURCE),
    ClassifyRule("source-suffix", "*.vue", ResourceKind.SOURCE),
)


def classify(
    path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> ResourceKind:
    """Classify one path, treating anything outside ``workspace_root`` as external."""
    if is_device_namespace(path):
        return ResourceKind.EXTERNAL
    relative = _relative_posix(path, workspace_root)
    if relative is None:
        return ResourceKind.EXTERNAL
    name = PurePosixPath(relative).name.casefold()

    for pattern, kind in _override_rules(overrides):
        if _matches(pattern, relative, name):
            return kind
    for rule in DEFAULT_CLASSIFY_RULES:
        if _matches(rule.pattern, relative, name):
            return rule.kind
    return ResourceKind.OTHER


def classify_with_reason(
    path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> tuple[ResourceKind, str]:
    """Same as :func:`classify`, plus the id of the winning rule (for audit)."""
    if is_device_namespace(path):
        return ResourceKind.EXTERNAL, "device-namespace"
    relative = _relative_posix(path, workspace_root)
    if relative is None:
        return ResourceKind.EXTERNAL, "external"
    name = PurePosixPath(relative).name.casefold()
    for pattern, kind in _override_rules(overrides):
        if _matches(pattern, relative, name):
            return kind, f"override:{pattern}"
    for rule in DEFAULT_CLASSIFY_RULES:
        if _matches(rule.pattern, relative, name):
            return rule.kind, rule.id
    return ResourceKind.OTHER, "default"


def _relative_posix(path: str | Path, workspace_root: str | Path | None) -> str | None:
    if is_device_namespace(path):
        return None
    raw = PurePosixPath(str(path).replace("\\", "/"))
    if ".." in raw.parts:
        return None
    if workspace_root is None:
        return str(raw)
    root = Path(str(workspace_root)).resolve()
    candidate = Path(str(path))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def _override_rules(overrides: Mapping[str, str] | None) -> tuple[tuple[str, ResourceKind], ...]:
    if not overrides:
        return ()
    rules: list[tuple[str, ResourceKind]] = []
    for pattern, kind in overrides.items():
        try:
            rules.append((pattern, ResourceKind(kind)))
        except ValueError as exc:
            raise ValueError(f"Unknown ResourceKind {kind!r} in [security.classify]") from exc
    return tuple(rules)


def _matches(pattern: str, relative: str, name: str) -> bool:
    """Match against the relative path or, for name-oriented patterns, the basename."""
    target = pattern.casefold()
    if fnmatch(relative.casefold(), target):
        return True
    if "/" not in pattern:
        return fnmatch(name, target)
    return False


def classify_many(
    paths: Sequence[str | Path],
    *,
    workspace_root: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, ResourceKind]:
    return {
        str(path): classify(path, workspace_root=workspace_root, overrides=overrides)
        for path in paths
    }


class ResourceClassifier:
    """Backwards-compatible façade over :func:`classify`."""

    @staticmethod
    def classify(
        path: Path,
        *,
        root: Path | None = None,
        overrides: Mapping[str, str] | None = None,
    ) -> ResourceKind:
        return classify(path, workspace_root=root, overrides=overrides)

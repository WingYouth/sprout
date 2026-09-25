"""Single source of truth for the on-disk skills layout.

Design references: §7.2 (index), §8.1 (source table).

Layout under ``~/.sprout/skills`` (``settings.skills_dir``)::

    <root>/
    ├── <name>.toml            # single-file skill
    ├── <name>/SKILL.md        # directory skill
    ├── .evolved/              # self-evolution products
    ├── .fetched/              # downloaded third-party skills
    ├── .quarantine/           # staged, not yet trusted
    └── .hub/
        └── index.json         # derived snapshot of the registry (§7.2)

The registry itself — what is installed, from where, trusted or not — lives in
``sprout_audit.db`` (design §10); ``index.json`` is written from it, never edited.

Keeping the names here — instead of inlining them in the broker, the CLI and
the loader — avoids the "parallel mechanism" trap: one place to define, one
place to read. ``skills_dir`` itself comes from ``Settings.skills_dir``.
"""

from __future__ import annotations

from pathlib import Path

HUB_DIRNAME = ".hub"
INDEX_FILENAME = "index.json"
#: Candidates discovered by crawling, which are *not* installed. Kept out of
#: ``index.json`` on purpose: that file is the authoritative snapshot of what is
#: installed and is what the L0 injection and the matcher read, so listing
#: uninstalled candidates there would leak them into the prompt.
REMOTE_INDEX_FILENAME = "remote.json"
QUARANTINE_DIRNAME = ".quarantine"
FETCHED_DIRNAME = ".fetched"
EVOLVED_DIRNAME = ".evolved"

#: Sources whose products live under ``.evolved/`` (self-evolution).
EVOLVED_SOURCES = frozenset({"evolved"})
#: Sources installed in place at the skills root (user-authored / project).
IN_PLACE_SOURCES = frozenset({"local", "project"})


def hub_dir(root: str | Path) -> Path:
    """Directory holding the derived index snapshot."""
    return Path(root) / HUB_DIRNAME


def index_path(root: str | Path) -> Path:
    """Path of the summary index (§7.2)."""
    return hub_dir(root) / INDEX_FILENAME


def remote_index_path(root: str | Path) -> Path:
    """Path of the crawled-candidate cache (not installed, not injected)."""
    return hub_dir(root) / REMOTE_INDEX_FILENAME


def quarantine_dir(root: str | Path) -> Path:
    """Staging area for downloaded, not-yet-trusted skills (§8.2)."""
    return Path(root) / QUARANTINE_DIRNAME


def install_target(root: str | Path, source: str, name: str) -> Path:
    """Final home for a skill coming from ``source`` (design §8.1).

    ``evolved`` → ``.evolved/<name>``; ``local``/``project`` → ``<root>/<name>``;
    everything else (catalog/github/url) → ``.fetched/<name>``.
    """
    base = Path(root)
    if source in EVOLVED_SOURCES:
        return base / EVOLVED_DIRNAME / name
    if source in IN_PLACE_SOURCES:
        return base / name
    return base / FETCHED_DIRNAME / name

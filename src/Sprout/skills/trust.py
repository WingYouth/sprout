"""Install-time staging: the quarantine a freshly downloaded skill lands in (§8.2).

The trust *ledger* that used to live here (``.hub/lock.json``) is gone. What was
installed, from where, and whether it is trusted now lives in the skill registry
(design §10, :class:`~Sprout.storage.contracts.skills.SkillStore`); ``.hub/index.json``
is the derived snapshot. This module keeps only the filesystem half.

:class:`Quarantine` is the staging directory a freshly downloaded skill lands in.
Nothing is loaded from here; only :meth:`Quarantine.promote` moves a skill out, and
that happens after a scan and an approval (design §7.4).
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path


class Quarantine:
    """The staging directory for downloaded skills: nothing runs from here."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path(self, name: str) -> Path:
        return self._root / _safe_name(name)

    def stage(self, name: str, files: Mapping[str, bytes]) -> Path:
        """Write a downloaded bundle into the quarantine; returns its directory."""
        target = self.path(name)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        for relative, content in files.items():
            destination = target / _safe_relative(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return target

    def list(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(entry.name for entry in self._root.iterdir() if entry.is_dir())

    def promote(self, name: str, destination: str | Path) -> Path:
        """Move a staged skill *directory* to its final home; returns the path."""
        source = self.path(name)
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(source), str(target))
        return target

    def promote_file(self, name: str, relative: str, destination: str | Path) -> Path:
        """Move one staged *file* to its final home; returns the path.

        Single-file (``.toml``) skills are the reason this exists: their
        convention is ``<root>/<name>.toml`` (see ``SkillRepository``), not
        ``<root>/<name>/<name>.toml``. Promoting the whole staging directory
        instead put the file one level too deep, where nothing ever looked for
        it — the install reported success and the skill stayed invisible.
        """
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.path(name) / _safe_relative(relative)
        if not source.is_file():
            raise FileNotFoundError(f"{relative!r} is not staged for {name!r}")
        destination_file = target
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(source), str(destination_file))
        # Drop the now-empty staging directory so a later install of the same
        # name does not find stale files beside the promoted one.
        shutil.rmtree(self.path(name), ignore_errors=True)
        return destination_file

    def discard(self, name: str) -> bool:
        target = self.path(name)
        if not target.exists():
            return False
        shutil.rmtree(target, ignore_errors=True)
        return True


def _safe_name(name: str) -> str:
    """Reject path traversal in a skill name."""
    cleaned = name.strip().replace("\\", "/").split("/")[-1]
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"Unsafe skill name: {name!r}")
    return cleaned


def _safe_relative(relative: str) -> Path:
    """Reject absolute paths and ``..`` escapes inside a staged bundle."""
    path = Path(relative.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe bundle path: {relative!r}")
    return path

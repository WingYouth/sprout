"""The on-disk layout is a single source of truth (design §7.2/§8.1)."""

from __future__ import annotations

from pathlib import Path

from Sprout.skills.layout import (
    EVOLVED_DIRNAME,
    FETCHED_DIRNAME,
    HUB_DIRNAME,
    INDEX_FILENAME,
    QUARANTINE_DIRNAME,
    index_path,
    install_target,
    quarantine_dir,
)
from Sprout.skills.trust import Quarantine


def test_hub_artifacts_live_under_dot_hub(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    assert index_path(root) == root / HUB_DIRNAME / INDEX_FILENAME
    assert quarantine_dir(root) == root / QUARANTINE_DIRNAME


def test_layout_names_match_design_doc() -> None:
    # §7.2 — the names the design doc pins down. The install ledger is no longer
    # a file here: it lives in the skill registry (§10).
    assert HUB_DIRNAME == ".hub"
    assert INDEX_FILENAME == "index.json"
    assert QUARANTINE_DIRNAME == ".quarantine"
    assert FETCHED_DIRNAME == ".fetched"
    assert EVOLVED_DIRNAME == ".evolved"


def test_install_target_by_source(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    # user-authored / project skills live in place at the root
    assert install_target(root, "local", "pdf") == root / "pdf"
    assert install_target(root, "project", "pdf") == root / "pdf"
    # self-evolution products go to .evolved/
    assert install_target(root, "evolved", "pdf") == root / ".evolved" / "pdf"
    # anything downloaded goes to .fetched/
    for source in ("catalog", "github", "url"):
        assert install_target(root, source, "pdf") == root / ".fetched" / "pdf"


def test_promote_composition_puts_downloaded_skill_in_fetched(tmp_path: Path) -> None:
    """The exact composition the broker uses: stage in quarantine → promote."""
    root = tmp_path / "skills"
    quarantine = Quarantine(quarantine_dir(root))
    quarantine.stage("pdf", {"SKILL.md": b"# pdf\n"})

    target = install_target(root, "catalog", "pdf")
    assert quarantine.promote("pdf", target) == root / ".fetched" / "pdf"
    assert (root / ".fetched" / "pdf" / "SKILL.md").is_file()
    assert not quarantine.path("pdf").exists()

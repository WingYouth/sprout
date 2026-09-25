"""Path-based resource classification (legacy module path).

The rule table moved to :mod:`Sprout.workspace.classifier` so there is exactly
one authoritative answer to "what kind is this file?". This module stays as the
import-stable façade used by the scanner and the security tests.
"""

from __future__ import annotations

from pathlib import Path

from Sprout.workspace.classifier import (
    DEFAULT_CLASSIFY_RULES,
    ClassifyRule,
    ResourceClassifier,
    classify,
    classify_many,
    classify_with_reason,
)
from Sprout.workspace.models import ResourceKind

__all__ = [
    "DEFAULT_CLASSIFY_RULES",
    "ClassifyRule",
    "ResourceClassifier",
    "classify",
    "classify_many",
    "classify_with_reason",
    "classify_path",
]


def classify_path(path: Path, *, root: Path | None = None) -> ResourceKind:
    """Compatibility helper for callers that still import from this module."""
    return classify(path, workspace_root=root)

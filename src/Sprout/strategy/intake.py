"""Normalize user suggestions and scan-generated evolution suggestions."""

from __future__ import annotations

from collections.abc import Mapping

from Sprout.strategy.models import Requirement, RequirementSource


class RequirementIntake:
    """Convert supported external shapes into a :class:`Requirement`."""

    def from_user(
        self,
        text: str,
        *,
        language: str = "",
        context: Mapping[str, object] | None = None,
    ) -> Requirement:
        return self._build(text, RequirementSource.USER, language, context)

    def from_scan(
        self,
        suggestion: str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> Requirement:
        return self._build(suggestion, RequirementSource.PROJECT_SCAN, "", context)

    def from_evolution(
        self,
        suggestion: str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> Requirement:
        return self._build(suggestion, RequirementSource.EVOLUTION, "", context)

    @staticmethod
    def _build(
        text: str,
        source: RequirementSource,
        language: str,
        context: Mapping[str, object] | None,
    ) -> Requirement:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Requirement text must not be empty")
        return Requirement(
            text=normalized,
            source=source,
            language=language,
            context=dict(context or {}),
        )

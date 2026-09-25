"""Requirement → skill matching over the local index (design §7.5).

Intentionally simple: keyword/tag scoring only. Semantic search is deferred
(decision Q-C) so this phase stays dependency-free and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from Sprout.skills.index import SkillIndex
from Sprout.skills.models import SkillRecord, TrustLevel

#: Small stopword set; matching is language-agnostic beyond this.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "to", "for", "of", "and", "or", "in", "on", "with",
        "please", "help", "me", "my", "i", "is", "it", "can", "you",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class SkillHit:
    """One match, with the evidence that produced it."""

    record: SkillRecord
    score: float
    matched_on: tuple[str, ...] = ()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.casefold())
        if token not in _STOPWORDS and len(token) > 1
    }


class SkillMatcher:
    """Rank index entries against a free-text requirement."""

    def match(
        self,
        query: str,
        index: SkillIndex,
        *,
        limit: int = 5,
        injectable_only: bool = True,
    ) -> list[SkillHit]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        hits: list[SkillHit] = []
        for record in index.load():
            if not record.enabled:
                continue
            if injectable_only and record.trust != TrustLevel.TRUSTED.value:
                continue
            hit = self._score(record, query, query_tokens)
            if hit is not None:
                hits.append(hit)
        hits.sort(key=lambda hit: (-hit.score, hit.record.name))
        return hits[:limit]

    @staticmethod
    def _score(record: SkillRecord, query: str, query_tokens: set[str]) -> SkillHit | None:
        matched: list[str] = []
        score = 0.0

        if query.strip().casefold() == record.name.casefold():
            matched.append("name")
            score += 10.0

        tag_hits = query_tokens & {tag.casefold() for tag in record.tags}
        if tag_hits:
            matched.append("tags")
            score += 3.0 * len(tag_hits)

        name_hits = query_tokens & _tokens(record.name)
        if name_hits:
            matched.append("name_tokens")
            score += 2.0 * len(name_hits)

        description_hits = query_tokens & _tokens(record.description)
        if description_hits:
            matched.append("description")
            score += 1.0 * len(description_hits)

        if score <= 0:
            return None
        return SkillHit(record=record, score=score, matched_on=tuple(matched))

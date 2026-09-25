"""Knowledge store contract: knowledge, FAQs, procedures, and topics.

This is the data behind ``sprout_knowledge.db`` in the local-first layout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

KNOWLEDGE = "knowledge"
FAQ = "faq"
PROCEDURE = "procedure"
TOPIC = "topic"


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    id: str
    content: str
    kind: str = KNOWLEDGE
    evidence_ids: tuple[str, ...] = ()
    version: int = 1
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Guidance §19.2 KnowledgeItem columns. Appended (not interleaved) so the
    # original positional order stays intact for existing constructors.
    scope: str = "global"
    title: str = ""
    content_blob_uri: str | None = None
    confidence: float = 1.0
    updated_at: datetime | None = None


class KnowledgeStore(Protocol):
    async def search(self, query: str, limit: int = 5) -> Sequence[KnowledgeItem]: ...
    async def put(self, item: KnowledgeItem) -> None: ...
    async def get(self, item_id: str) -> KnowledgeItem | None: ...
    async def list_items(
        self, kind: str | None = None, limit: int = 100
    ) -> Sequence[KnowledgeItem]: ...
    async def count(self) -> int: ...

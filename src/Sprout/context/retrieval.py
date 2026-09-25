"""Retrieval helpers feeding knowledge into the agent context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from Sprout.message.models import Message

if TYPE_CHECKING:
    from Sprout.storage.contracts.knowledge import KnowledgeItem, KnowledgeStore


class KnowledgeRetriever:
    """Keyword retrieval today; a vector store can slot in behind the same call."""

    def __init__(self, knowledge: KnowledgeStore, *, limit: int = 5) -> None:
        self._knowledge = knowledge
        self._limit = limit

    async def retrieve(self, query: str) -> Sequence[KnowledgeItem]:
        if not query.strip():
            return ()
        return await self._knowledge.search(query, limit=self._limit)

    async def retrieve_for(self, message: Message) -> Sequence[KnowledgeItem]:
        return await self.retrieve(message.content)

"""In-memory knowledge store with simple keyword ranking."""

from __future__ import annotations

from uuid import uuid4

from Sprout.storage.contracts.knowledge import KnowledgeItem


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self.items: dict[str, KnowledgeItem] = {}

    async def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        words = {word.casefold() for word in query.split() if word.strip()}
        if not words:
            return []
        ranked = sorted(
            self.items.values(),
            key=lambda item: len(words.intersection(item.content.casefold().split())),
            reverse=True,
        )
        return [
            item
            for item in ranked
            if item.status == "active"
            and any(word in item.content.casefold() for word in words)
        ][:limit]

    async def put(self, item: KnowledgeItem) -> None:
        self.items[item.id] = item

    async def get(self, item_id: str) -> KnowledgeItem | None:
        return self.items.get(item_id)

    async def list_items(
        self, kind: str | None = None, limit: int = 100
    ) -> list[KnowledgeItem]:
        items = [
            item
            for item in self.items.values()
            if (kind is None or item.kind == kind) and item.status == "active"
        ]
        return items[:limit]

    async def count(self) -> int:
        return len(self.items)


def new_knowledge_item(content: str, *, kind: str = "knowledge") -> KnowledgeItem:
    return KnowledgeItem(id=str(uuid4()), content=content, kind=kind)

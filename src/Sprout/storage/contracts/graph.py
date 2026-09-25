"""Graph store contract: the derived lane for entity relations.

Fills the ``GraphStore (pending)`` slot in the data-layer plan. A graph store
never holds authoritative data — every node and relation is a *projection* of
an entity owned by an authority lane (SQLite, JSONL, or the blobstore), which
means it can always be rebuilt and must cascade-delete with its source.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class GraphStore(Protocol):
    """Derived graph projections, keyed by one property per label."""

    async def merge_node(
        self, label: str, key_prop: str, props: dict[str, Any]
    ) -> None:
        """Idempotently create or update one node."""
        ...

    async def merge_relation(
        self,
        src_label: str,
        src_key: str,
        rel: str,
        dst_label: str,
        dst_key: str,
        *,
        src_prop: str = "id",
        dst_prop: str = "id",
        props: Mapping[str, Any] | None = None,
    ) -> None:
        """Idempotently create one relation between two existing nodes.

        ``props`` optionally carries a relation identity (for example an
        ``edge_id``) so multiple distinct relations of the same type between the
        same two nodes do not collapse into one projection.
        """
        ...

    async def drop_node(self, label: str, key_prop: str, key_value: str) -> int:
        """Detach-delete the node; returns how many nodes were removed."""
        ...


__all__ = ["GraphStore"]

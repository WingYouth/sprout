"""Milvus vector lane: the VectorStore contract over a real Milvus server.

Each namespace maps to its own collection (``sprout_vec_{namespace}``), so
session turns, knowledge chunks, memory facts, and context snapshots share one
deployment without cross-talk. Vectors are supplied by the caller — the
runtime embeds with :class:`~Sprout.storage.embeddings.HashingEmbedder` by
default — and metadata is stored as a JSON string, surfaced back on search.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from typing import Any

from Sprout.rootstock.backends.milvus_store import normalize_uri
from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.storage.contracts.vectors import VectorHit

DEFAULT_DIM = 1536


def _require_pymilvus(dsn: str) -> None:
    if importlib.util.find_spec("pymilvus") is None:
        raise RootstockUnavailableError(
            "The milvus vector lane requires the 'pymilvus' package. "
            f"Install it (e.g. `uv add pymilvus`) and set [storage] vectors = "
            f'"{dsn}".'
        )


class MilvusVectorStore:
    """Namespace-routed vector store backed by Milvus collections."""

    def __init__(self, dsn: str, *, dim: int = DEFAULT_DIM) -> None:
        _require_pymilvus(dsn)
        self.dsn = dsn
        self.dim = dim
        self._client: Any = None
        self._ready: set[str] = set()

    @staticmethod
    def collection_for(namespace: str) -> str:
        return f"sprout_vec_{namespace}"

    def _ensure_client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=normalize_uri(self.dsn))
        return self._client

    def _ensure_collection(self, namespace: str) -> str:
        collection = self.collection_for(namespace)
        if collection in self._ready:
            return collection
        client = self._ensure_client()
        from pymilvus import DataType

        if not client.has_collection(collection):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("key", DataType.VARCHAR, is_primary=True, max_length=255)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
            schema.add_field("metadata_json", DataType.VARCHAR, max_length=65535)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding", index_type="FLAT", metric_type="COSINE"
            )
            client.create_collection(
                collection, schema=schema, index_params=index_params
            )
        # search/query only serve loaded collections; loading is idempotent.
        client.load_collection(collection)
        self._ready.add(collection)
        return collection

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
            self._ready.clear()

    @staticmethod
    def _build_filter(filters: dict[str, Any] | None) -> str:
        if not filters:
            return 'key != ""'
        clauses = []
        for name, value in filters.items():
            if isinstance(value, str):
                clauses.append(f'{name} == "{value}"')
            else:
                clauses.append(f"{name} == {value}")
        return " and ".join(clauses)

    async def upsert(
        self,
        key: str,
        vector: Any,
        *,
        namespace: str = "session_turns",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        collection = self._ensure_collection(namespace)
        row = {
            "key": key,
            "embedding": list(vector),
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        }

        def _run() -> None:
            client = self._ensure_client()
            client.upsert(collection, [row])
            # Standalone Milvus serves queries at bounded consistency; flush
            # makes the write visible to an immediate read-back.
            client.flush(collection)

        await asyncio.to_thread(_run)

    async def search(
        self,
        vector: Any,
        limit: int = 5,
        *,
        namespace: str = "session_turns",
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        """Metadata-level filtering: candidates are matched client-side.

        The Milvus metadata JSON string is matched against the requested
        filter values, so equality filters behave exactly like the in-memory
        store without a per-field schema per namespace.
        """
        collection = self._ensure_collection(namespace)

        def _run() -> list[dict]:
            return list(
                self._ensure_client().search(
                    collection,
                    data=[list(vector)],
                    limit=min(limit * 10, 256),
                    output_fields=["metadata_json"],
                    filter='key != ""',
                )
            )

        raw = await asyncio.to_thread(_run)
        hits: list[VectorHit] = []
        if not raw:
            return hits
        for entry in raw[0]:
            metadata = json.loads(entry.get("metadata_json") or "{}")
            if filters and any(metadata.get(k) != v for k, v in filters.items()):
                continue
            hits.append(
                VectorHit(
                    key=entry.get("key") or entry.get("id", ""),
                    score=float(entry.get("distance", 0.0)),
                    namespace=namespace,
                    metadata=metadata,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def delete(self, key: str, *, namespace: str = "session_turns") -> bool:
        collection = self._ensure_collection(namespace)

        def _run() -> None:
            client = self._ensure_client()
            client.delete(collection, filter=f'key == "{key}"')
            # Standalone Milvus applies deletes asynchronously; flush makes a
            # read-after-delete see the row gone (Lite is already immediate).
            client.flush(collection)

        await asyncio.to_thread(_run)
        return True

    async def count(self, *, namespace: str | None = None) -> int:
        if namespace is not None:
            namespaces = [namespace]
        else:
            # Without an explicit namespace, count every collection that has
            # been touched in this process (Milvus has no list-and-count-all).
            namespaces = list(self._ready)
        total = 0
        for ns in namespaces:
            collection = self._ensure_collection(ns)
            client = self._ensure_client()

            def _run(coll: str = collection, cl: Any = client) -> list[dict]:
                return list(
                    cl.query(coll, filter='key != ""', output_fields=["count(*)"])
                )

            rows = await asyncio.to_thread(_run)
            if rows:
                total += int(rows[0]["count(*)"])
        return total


__all__ = ["DEFAULT_DIM", "MilvusVectorStore"]

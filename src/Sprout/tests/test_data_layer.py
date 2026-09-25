"""Data-layer tests: the plan is complete, and the vector lane round-trips."""

from __future__ import annotations

import pytest

from Sprout.config.settings import StorageSettings
from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.storage.bundle import create_storage, storage_status
from Sprout.storage.contracts.vectors import (
    KNOWLEDGE_CHUNKS,
    SESSION_TURNS,
    SKILLS,
    VectorHit,
)
from Sprout.storage.local.memory.vectors import MemoryVectorStore
from Sprout.storage.plan import DATA_LAYER, authority_keys, data_layer_plan, entry_for

# -- the plan ---------------------------------------------------------------


def test_plan_covers_the_six_data_layer_databases() -> None:
    assert [entry.key for entry in DATA_LAYER] == [
        "sqlite",
        "jsonl",
        "blobstore",
        "redis",
        "milvus",
        "neo4j",
    ]


def test_every_entry_declares_contract_and_retention() -> None:
    for entry in DATA_LAYER:
        assert entry.contract, entry.key
        assert entry.responsibility, entry.key
        assert entry.owns, entry.key
        assert entry.retention, entry.key
        assert entry.lane in {"authority", "capability", "evidence"}, entry.key


def test_only_durable_stores_can_hold_authoritative_data() -> None:
    # Cache, vector index, and graph are always derived, never authoritative.
    assert set(authority_keys()) == {"sqlite", "jsonl", "blobstore"}
    for key in ("redis", "milvus", "neo4j"):
        assert entry_for(key).authority is False


def test_entry_lookup_and_resolution(tmp_path) -> None:
    assert entry_for("milvus").authority is False
    with pytest.raises(KeyError):
        entry_for("postgres")

    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        session=f"sqlite:///{tmp_path / 'session.db'}",
    )
    resolved = {row["key"]: row["dsn"] for row in data_layer_plan(settings)}
    assert str(tmp_path / "runtime.db") in str(resolved["sqlite"])
    assert resolved["redis"] == "memory"
    assert resolved["milvus"] == "memory"


# -- vector lane ------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_vector_store_ranks_by_cosine_similarity() -> None:
    store = MemoryVectorStore()
    await store.upsert("near", [1.0, 0.0], metadata={"session_id": "s-1"})
    await store.upsert("far", [0.0, 1.0], metadata={"session_id": "s-1"})

    hits = await store.search([0.9, 0.1])
    assert [hit.key for hit in hits] == ["near", "far"]
    assert isinstance(hits[0], VectorHit)
    assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_memory_vector_store_isolates_namespaces_and_filters() -> None:
    store = MemoryVectorStore()
    await store.upsert("t-1", [1.0, 0.0], metadata={"session_id": "s-1"})
    await store.upsert("t-2", [1.0, 0.0], metadata={"session_id": "s-2"})
    await store.upsert("k-1", [1.0, 0.0], namespace=KNOWLEDGE_CHUNKS)

    assert await store.count() == 3
    assert await store.count(namespace=SESSION_TURNS) == 2

    only_first = await store.search([1.0, 0.0], filters={"session_id": "s-1"})
    assert [hit.key for hit in only_first] == ["t-1"]

    knowledge = await store.search([1.0, 0.0], namespace=KNOWLEDGE_CHUNKS)
    assert [hit.key for hit in knowledge] == ["k-1"]


@pytest.mark.asyncio
async def test_memory_vector_store_delete_and_edge_cases() -> None:
    store = MemoryVectorStore()
    await store.upsert("t-1", [0.0, 0.0], namespace=SKILLS)
    await store.upsert("t-2", [1.0])

    # Zero vectors and length mismatches score 0.0 rather than raising.
    hits = await store.search([1.0, 2.0], namespace=SKILLS)
    assert hits[0].score == 0.0

    assert await store.delete("t-1", namespace=SKILLS) is True
    assert await store.delete("t-1", namespace=SKILLS) is False
    assert await store.count(namespace=SKILLS) == 0


# -- bundle wiring ----------------------------------------------------------


@pytest.mark.asyncio
async def test_bundle_carries_the_vector_lane(tmp_path) -> None:
    settings = StorageSettings(
        operational=f"sqlite:///{tmp_path / 'runtime.db'}",
        knowledge=f"sqlite:///{tmp_path / 'knowledge.db'}",
        session=f"sqlite:///{tmp_path / 'session.db'}",
    )
    bundle = create_storage(settings)

    assert isinstance(bundle.vectors, MemoryVectorStore)
    status = await storage_status(bundle)
    assert status["vectors"] == 0

    await bundle.close()


def test_unknown_vector_dsn_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported vectors DSN"):
        create_storage(StorageSettings(vectors="qdrant://localhost"))


def test_milvus_vector_dsn_reports_missing_client() -> None:
    import importlib.util

    if importlib.util.find_spec("pymilvus") is not None:  # pragma: no cover
        pytest.skip("pymilvus installed; the reserved error path is covered elsewhere")
    with pytest.raises(RootstockUnavailableError, match="vectors"):
        create_storage(StorageSettings(vectors="milvus://localhost:19530"))


# -- runtime visibility -----------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_describes_the_whole_data_layer() -> None:
    from Sprout.tests.conftest import build_runtime

    runtime, _ = build_runtime()
    storage = runtime.describe().storage
    for key in ("sessions", "operational", "knowledge", "metadata", "vectors", "cache"):
        assert key in storage, key
    assert storage["vectors"] == "MemoryVectorStore"

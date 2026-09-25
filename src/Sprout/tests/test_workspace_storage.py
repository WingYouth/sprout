"""Tests for workspace-facing storage integrations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.embeddings import ApiEmbedder, make_embedder
from Sprout.storage.local.sqlite.knowledge import open_knowledge_store
from Sprout.workspace.graph import _extract_generic_symbols


def test_knowledge_sqlite_fts_search(tmp_path: Path) -> None:
    store = open_knowledge_store(str(tmp_path / "knowledge.db"))

    async def run() -> None:
        await store.put(
            KnowledgeItem(
                id="a",
                content="python workspace graph",
                kind="fact",
                evidence_ids=("x",),
                created_at=datetime.now(UTC),
            )
        )
        await store.put(
            KnowledgeItem(
                id="b",
                content="deploy blue cluster",
                kind="fact",
                evidence_ids=("y",),
                created_at=datetime.now(UTC),
            )
        )
        assert [item.id for item in await store.search("python")] == ["a"]
        assert [item.id for item in await store.search("blue cluster")] == ["b"]
        store.close()

    asyncio.run(run())


def test_generic_symbol_extraction(tmp_path: Path) -> None:
    go = tmp_path / "x.go"
    go.write_text(
        "package main\nfunc main() {}\ntype Server struct {}\n",
        encoding="utf-8",
    )
    assert ("main", "function", 2) in _extract_generic_symbols(go, ".go")
    assert ("Server", "class", 3) in _extract_generic_symbols(go, ".go")

    ts = tmp_path / "y.ts"
    ts.write_text(
        "export function foo() {}\nclass Bar {}\nconst baz = () => 1;\n",
        encoding="utf-8",
    )
    names = {name for name, _, _ in _extract_generic_symbols(ts, ".ts")}
    assert {"foo", "Bar", "baz"} <= names


def test_embedder_falls_back_to_hashing() -> None:
    unconfigured = ApiEmbedder(base_url="", model="", api_key="", dim=1536)
    assert unconfigured.configured is False

    async def run() -> None:
        vector = await unconfigured.embed("hello world")
        assert len(vector) == 1536
        assert vector == await unconfigured.embed("hello world")

    asyncio.run(run())


def test_make_embedder_builds_an_embedder() -> None:
    embedder = make_embedder()
    assert hasattr(embedder, "dim")
    assert hasattr(embedder, "embed")

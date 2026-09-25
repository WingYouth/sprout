"""Skill registry tests (design §10): the memory and SQLite stores must agree."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from Sprout.skills.models import SkillRecord
from Sprout.storage.contracts.skills import SkillStore
from Sprout.storage.local.memory import MemorySkillStore
from Sprout.storage.local.sqlite.skills import open_skill_store


def _record(name: str, **overrides: object) -> SkillRecord:
    fields: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "description": f"{name} skill",
        "tags": ("a", "b"),
        "source": "catalog",
        "origin": f"catalog://{name}",
        "digest": f"sha256:{name}",
        "trust": "untrusted",
        "path": f"/skills/{name}",
    }
    fields.update(overrides)
    return SkillRecord(**fields)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SkillStore]:
    """Both implementations, driven through the same contract."""
    if request.param == "memory":
        yield MemorySkillStore()
        return
    opened = open_skill_store(str(tmp_path / "sprout_audit.db"))
    yield opened
    opened.close()


async def test_upsert_then_get_round_trips_every_field(store: SkillStore) -> None:
    record = _record("pdf")
    await store.upsert(record)

    loaded = await store.get("pdf")

    assert loaded == record


async def test_get_missing_returns_none(store: SkillStore) -> None:
    assert await store.get("nope") is None


async def test_upsert_replaces_by_name(store: SkillStore) -> None:
    await store.upsert(_record("pdf"))
    await store.upsert(_record("pdf", version="2.0.0", description="newer"))

    loaded = await store.get("pdf")

    assert loaded is not None
    assert loaded.version == "2.0.0"
    assert loaded.description == "newer"
    assert len(await store.list()) == 1


async def test_list_filters_by_source_trust_and_enabled(store: SkillStore) -> None:
    await store.upsert(_record("a", source="catalog", trust="trusted"))
    await store.upsert(_record("b", source="catalog", trust="untrusted"))
    await store.upsert(_record("c", source="local", trust="trusted", enabled=False))

    assert [r.name for r in await store.list()] == ["a", "b", "c"]
    assert [r.name for r in await store.list(source="catalog")] == ["a", "b"]
    assert [r.name for r in await store.list(trust="trusted")] == ["a", "c"]
    assert [r.name for r in await store.list(enabled_only=True)] == ["a", "b"]
    assert [
        r.name for r in await store.list(source="catalog", trust="trusted", enabled_only=True)
    ] == ["a"]


async def test_set_enabled_and_set_trust(store: SkillStore) -> None:
    await store.upsert(_record("pdf"))

    await store.set_enabled("pdf", False)
    await store.set_trust("pdf", "trusted")

    loaded = await store.get("pdf")
    assert loaded is not None
    assert loaded.enabled is False
    assert loaded.trust == "trusted"


async def test_set_on_missing_name_is_a_noop(store: SkillStore) -> None:
    await store.set_enabled("ghost", False)
    await store.set_trust("ghost", "trusted")

    assert await store.list() == []


async def test_remove_drops_the_record(store: SkillStore) -> None:
    await store.upsert(_record("pdf"))

    await store.remove("pdf")

    assert await store.get("pdf") is None
    assert await store.list() == []


async def test_remove_missing_is_a_noop(store: SkillStore) -> None:
    await store.remove("ghost")

    assert await store.list() == []


async def test_is_trusted_requires_trusted_and_matching_digest(store: SkillStore) -> None:
    await store.upsert(_record("pdf", trust="trusted", digest="sha256:good"))

    assert await store.is_trusted("pdf", "sha256:good") is True
    # changed content -> different digest -> must be re-reviewed (§8.4)
    assert await store.is_trusted("pdf", "sha256:other") is False
    assert await store.is_trusted("ghost", "sha256:good") is False

    await store.set_trust("pdf", "untrusted")
    assert await store.is_trusted("pdf", "sha256:good") is False


async def test_upsert_after_remove_starts_clean(store: SkillStore) -> None:
    await store.upsert(_record("pdf"))
    await store.remove("pdf")
    await store.upsert(_record("pdf", version="9.9.9"))

    loaded = await store.get("pdf")

    assert loaded is not None
    assert loaded.version == "9.9.9"

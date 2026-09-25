"""Tests for Weixin iLink per-peer state persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from Sprout.gateway.channels.weixin_ilink_state import WeixinIlinkStateStore


def test_state_store_round_trips_peer_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    async def run() -> None:
        store = WeixinIlinkStateStore(path)
        await store.set_context_token("peer-1", "ctx-1")
        await store.set_session_id("peer-1", "session-1")
        await store.set_last_task_id("peer-1", "task-1")
        await store.set_sync_buf("sync-buf-1")

        reloaded = WeixinIlinkStateStore(path)
        assert await reloaded.get_context_token("peer-1") == "ctx-1"
        assert await reloaded.get_session_id("peer-1") == "session-1"
        assert await reloaded.get_last_task_id("peer-1") == "task-1"
        assert await reloaded.get_sync_buf() == "sync-buf-1"

    asyncio.run(run())


def test_state_store_migrates_legacy_context_tokens(tmp_path: Path) -> None:
    legacy = tmp_path / "context.json"
    legacy.write_text(
        json.dumps({"peer-1": "legacy-ctx"}),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"

    async def run() -> None:
        store = WeixinIlinkStateStore(
            state,
            legacy_context_path=legacy,
        )
        assert await store.get_context_token("peer-1") == "legacy-ctx"

    asyncio.run(run())

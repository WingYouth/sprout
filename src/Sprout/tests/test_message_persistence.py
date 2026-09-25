"""Message persistence strategy tests (MESSAGE_PERSISTENCE.md M1-M4).

Guards, one per load-bearing property:

- P2 envelope lossless round trip (``turn_envelope``/``message_from_turn``)
- M1 runtime persists envelopes on the authority turns
- M2 the observation recorder lands the message lifecycle; fail-open and
  log-only (no recursion), payload clamping
- P5 legacy SQLite databases migrate to the envelope column
- M3 oversized bodies offload to the blobstore and resolve back; a failing
  blobstore degrades to inline instead of losing the turn
- P1 the runtime is the only authority ``append_turn`` write point
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from Sprout.events import EventBus
from Sprout.events.event import Event
from Sprout.events.recorder import MAX_PAYLOAD_CHARS, ObservationRecorder
from Sprout.events.types import MESSAGE_PERSISTED, MESSAGE_RECEIVED, MESSAGE_SENT
from Sprout.message.converter import (
    assistant_envelope,
    message_from_turn,
    turn_envelope,
)
from Sprout.message.models import Message
from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
from Sprout.rootstock.backends.sqlite_store import open_session_store
from Sprout.session.models import Turn
from Sprout.tests.conftest import build_runtime

# -- P2: envelope round trip -------------------------------------------------


def test_turn_envelope_round_trip() -> None:
    message = Message(
        "hello",
        channel="cli",
        user_id="u-1",
        session_id="s-1",
        metadata={"ticket": "T-42"},
    )
    turn = Turn("s-1", "user", "hello", metadata=turn_envelope(message))

    rebuilt = asyncio.run(message_from_turn(turn))

    assert rebuilt.content == "hello"
    assert rebuilt.channel == "cli"
    assert rebuilt.user_id == "u-1"
    assert rebuilt.session_id == "s-1"
    assert rebuilt.id == message.id
    assert rebuilt.metadata["ticket"] == "T-42"


def test_assistant_envelope_carries_correlation_and_agent() -> None:
    message = Message("hello", channel="web", user_id="u-1")
    envelope = assistant_envelope(message, {"steps": 2, "truncated": False})

    assert envelope["correlation_id"] == message.id
    assert envelope["channel"] == "web"
    assert envelope["agent"] == {"steps": 2, "truncated": False}


# -- M1: runtime persists envelopes ------------------------------------------


@pytest.mark.asyncio
async def test_handle_persists_envelope_on_authority_turns() -> None:
    runtime, _ = build_runtime()
    message = Message("hello", channel="cli", user_id="u-1", metadata={"k": "v"})

    reply = await runtime.handle(message)
    turns = await runtime.history(reply.session_id)

    assert [turn.role for turn in turns] == ["user", "assistant"]
    user_envelope = turns[0].metadata
    assert user_envelope["channel"] == "cli"
    assert user_envelope["user_id"] == "u-1"
    assert user_envelope["message_id"] == message.id
    assert user_envelope["message_metadata"] == {"k": "v"}

    assistant_meta = turns[1].metadata
    assert assistant_meta["correlation_id"] == message.id
    assert assistant_meta["channel"] == "cli"
    assert "agent" in assistant_meta  # AgentLoop surfaces step stats

    rebuilt = await message_from_turn(turns[0])
    assert rebuilt.id == message.id
    assert rebuilt.metadata == {"k": "v"}


@pytest.mark.asyncio
async def test_handle_publishes_message_persisted() -> None:
    runtime, _ = build_runtime()
    seen: list[Event] = []

    async def collect(event: Event) -> None:
        seen.append(event)

    runtime.events.subscribe(MESSAGE_PERSISTED, collect)

    reply = await runtime.handle(Message("hello"))

    persisted = [event for event in seen if event.name == MESSAGE_PERSISTED]
    assert len(persisted) == 1
    payload = persisted[0].payload
    assert payload["session_id"] == reply.session_id
    assert len(payload["turn_ids"]) == 2
    assert payload["seqs"] == [1, 2]


# -- M2: observation recorder ------------------------------------------------


@pytest.mark.asyncio
async def test_recorder_lands_message_lifecycle() -> None:
    runtime, _ = build_runtime()
    store = runtime.storage.observations
    assert store is not None
    runtime.events.subscribe("*", ObservationRecorder(store))
    before = await store.count_events()

    await runtime.handle(Message("hello"))

    events = list(await store.list_events(limit=50))
    names = {event.name for event in events}
    assert await store.count_events() >= before + 4
    assert MESSAGE_RECEIVED in names
    assert MESSAGE_PERSISTED in names
    assert MESSAGE_SENT in names


@pytest.mark.asyncio
async def test_recorder_fail_open_and_no_recursion() -> None:
    calls: list[str] = []

    class ExplodingStore:
        async def append_event(self, event: Event) -> None:
            calls.append(event.name)
            raise RuntimeError("observations lane down")

        async def append_reflection(self, reflection) -> None:  # pragma: no cover
            raise RuntimeError("observations lane down")

    bus = EventBus()
    bus.subscribe("*", ObservationRecorder(ExplodingStore()))  # type: ignore[arg-type]

    await bus.publish(Event(MESSAGE_RECEIVED, {"message_id": "m-1"}))
    await bus.publish(Event(MESSAGE_SENT, {"message_id": "m-1"}))

    # Fail-open: no exception escaped; log-only: exactly one attempt per
    # published event (a re-published audit event would recurse and inflate).
    assert calls == [MESSAGE_RECEIVED, MESSAGE_SENT]


@pytest.mark.asyncio
async def test_recorder_clamps_large_payloads() -> None:
    class RecordingStore:
        def __init__(self) -> None:
            self.events: list[Event] = []

        async def append_event(self, event: Event) -> None:
            self.events.append(event)

    store = RecordingStore()
    recorder = ObservationRecorder(store)  # type: ignore[arg-type]
    long_body = "x" * (MAX_PAYLOAD_CHARS * 3)

    await recorder(Event("tool.executed", {"output": long_body}))

    stored = store.events[0]
    clamped = stored.payload["output"]
    assert len(clamped) < len(long_body)
    assert clamped.endswith("…[truncated]")


# -- P5: legacy database migration -------------------------------------------


def test_sqlite_legacy_turns_table_migrates_envelope(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-session.db"
    # A pre-seq, pre-envelope schema: the oldest turns table in the wild.
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE turns ("
        "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, "
        "content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO turns VALUES ('t-legacy', 's-1', 'user', 'old row', "
        "'2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    store = open_session_store(str(db_path))

    legacy = asyncio.run(store.recent_turns("s-1"))
    assert [turn.id for turn in legacy] == ["t-legacy"]
    assert legacy[0].metadata == {}

    asyncio.run(
        store.append_turn(
            Turn(
                "s-1",
                "user",
                "new row",
                metadata=turn_envelope(
                    Message("new row", channel="cli", user_id="u-1")
                ),
            )
        )
    )
    turns = asyncio.run(store.recent_turns("s-1"))
    assert turns[-1].metadata["channel"] == "cli"
    assert turns[-1].metadata["user_id"] == "u-1"
    store.close()


def test_jsonl_store_preserves_envelope(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    store = JsonlSessionStore(path)
    envelope = turn_envelope(Message("hello", channel="web", user_id="u-9"))
    asyncio.run(store.append_turn(Turn("s-1", "user", "hello", metadata=envelope)))

    reopened = JsonlSessionStore(path)
    turns = asyncio.run(reopened.recent_turns("s-1"))
    assert turns[0].metadata["channel"] == "web"
    assert turns[0].metadata["user_id"] == "u-9"
    assert turns[0].metadata["message_id"] == envelope["message_id"]


# -- M3: oversized body offload ----------------------------------------------


@pytest.mark.asyncio
async def test_oversized_body_offloads_to_blobstore() -> None:
    runtime, _ = build_runtime()
    big = "y" * 20_000
    message = Message(big, channel="cli")

    reply = await runtime.handle(message)
    turns = await runtime.history(reply.session_id)

    user_turn = turns[0]
    assert "blob_uri" in user_turn.metadata
    assert len(user_turn.content) < len(big)  # preview stays inline

    rebuilt = await message_from_turn(user_turn, blobs=runtime.storage.blobs)
    assert rebuilt.content == big  # full body resolves back through the blob


@pytest.mark.asyncio
async def test_blobstore_failure_degrades_inline() -> None:
    runtime, _ = build_runtime()

    async def explode(data: bytes, *, mime_type: str) -> str:
        raise RuntimeError("blob lane down")

    assert runtime.storage.blobs is not None
    runtime.storage.blobs.put = explode  # type: ignore[method-assign]

    big = "z" * 20_000
    reply = await runtime.handle(Message(big))
    turns = await runtime.history(reply.session_id)

    # Fail-open: the full body stays inline, nothing is lost.
    assert turns[0].content == big
    assert "blob_uri" not in turns[0].metadata


# -- P1: single authority write point ----------------------------------------


def test_factory_wires_observation_recorder() -> None:
    """``create_runtime`` lands bus events in observations when wired (M2).

    Structural guard: every entry point (CLI/MCP/Web) assembles through the
    factory, so the subscription living there is what makes M2 real. Removing
    it must turn this test red (ablation-proven).
    """
    import Sprout.runtime.factory as factory

    source = Path(factory.__file__).read_text(encoding="utf-8")
    assert (
        'events.subscribe("*", ObservationRecorder(storage.observations))' in source
    )


def test_runtime_is_the_only_authority_append_turn_caller() -> None:
    """The online path has exactly one authority write point (P1).

    Backends, the lane fan-out, and the storage diagnostics are excluded:
    they *are* the write path. Anything else calling ``append_turn`` would
    open a second authority write point.
    """
    src_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in src_root.rglob("*.py"):
        relative = path.relative_to(src_root).as_posix()
        if any(
            part in relative
            for part in ("rootstock/", "storage/", "tests/", "web/")
        ):
            continue
        text = path.read_text(encoding="utf-8")
        if ".append_turn(" in text:
            offenders.append(relative)
    assert offenders == ["Sprout/runtime/runtime.py"], offenders

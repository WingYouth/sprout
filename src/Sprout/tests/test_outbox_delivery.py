"""The outbox must not lose derived writes — or pretend it delivered them.

A turn is written together with an outbox event in one transaction, so a crash
cannot leave a turn without its memory-index counterpart. The worker drains that
queue, and a failure correctly leaves the row pending for the next pass.

What it also did was swallow the exception and still count the event as
delivered. A derived write that could never succeed — a malformed payload, a
schema mismatch in the lane — retried forever with nothing logged, and the
caller saw the same progress as a healthy drain.
"""

from __future__ import annotations

import asyncio
import json
import logging

from Sprout.events import OUTBOX_TURN_INDEXED
from Sprout.memory.outbox import OutboxWorker, migrate_outbox
from Sprout.storage.local.sqlite.driver import SqliteDatabase


class _RecordingSearch:
    """A session search that either accepts turns or fails every one."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.indexed: list[dict] = []

    async def index_turn(self, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("index lane is down")
        self.indexed.append(kwargs)


def _db(tmp_path) -> SqliteDatabase:
    db = SqliteDatabase(str(tmp_path / "conv.db"))
    migrate_outbox(db)
    return db


def _append(db: SqliteDatabase, event_id: str = "e1", *, kind: str = OUTBOX_TURN_INDEXED) -> None:
    db.execute_sync(
        "INSERT INTO outbox (event_id, kind, session_id, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            event_id,
            kind,
            "s1",
            json.dumps({"turn_id": "t1", "seq": 1, "role": "user", "body": "hi"}),
            "2026-09-24T00:00:00+00:00",
        ),
    )


def test_a_pending_event_is_delivered_and_marked(tmp_path) -> None:
    db = _db(tmp_path)
    _append(db)
    search = _RecordingSearch()

    delivered = asyncio.run(
        OutboxWorker(db=db, session_search=search).drain_once(limit=10)
    )

    assert delivered == 1
    assert [item["turn_id"] for item in search.indexed] == ["t1"]
    assert asyncio.run(OutboxWorker(db=db).pending_count()) == 0


def test_a_failure_is_not_counted_as_delivered(tmp_path) -> None:
    """The count must mean "landed", not "attempted"."""
    db = _db(tmp_path)
    _append(db)
    search = _RecordingSearch(fail=True)

    delivered = asyncio.run(
        OutboxWorker(db=db, session_search=search).drain_once(limit=10)
    )

    assert delivered == 0, "a failed delivery was reported as progress"


def test_a_failure_is_logged_with_enough_to_act_on(tmp_path, caplog) -> None:
    """Silent retry is the failure mode this guards: nobody can see it."""
    db = _db(tmp_path)
    _append(db, "event-abc")
    search = _RecordingSearch(fail=True)

    with caplog.at_level(logging.WARNING, logger="sprout.memory.outbox"):
        asyncio.run(OutboxWorker(db=db, session_search=search).drain_once(limit=10))

    assert caplog.records, "the failure was swallowed without a trace"
    message = caplog.records[-1].getMessage()
    assert "event-abc" in message, "the log must name the event that is stuck"
    assert "RuntimeError" in message


def test_a_failed_event_stays_pending_for_the_next_pass(tmp_path) -> None:
    """The retry contract still holds: a failure must not drop the row."""
    db = _db(tmp_path)
    _append(db)
    search = _RecordingSearch(fail=True)

    asyncio.run(OutboxWorker(db=db, session_search=search).drain_once(limit=10))

    assert asyncio.run(OutboxWorker(db=db).pending_count()) == 1


def test_pending_count_distinguishes_idle_from_stuck(tmp_path, caplog) -> None:
    db = _db(tmp_path)
    _append(db, "e1")
    _append(db, "e2")
    search = _RecordingSearch(fail=True)

    with caplog.at_level(logging.WARNING, logger="sprout.memory.outbox"):
        asyncio.run(OutboxWorker(db=db, session_search=search).drain_once(limit=10))

    assert asyncio.run(OutboxWorker(db=db).pending_count()) == 2


def test_an_empty_outbox_reports_zero(tmp_path) -> None:
    db = _db(tmp_path)

    assert asyncio.run(OutboxWorker(db=db).drain_once(limit=10)) == 0
    assert asyncio.run(OutboxWorker(db=db).pending_count()) == 0

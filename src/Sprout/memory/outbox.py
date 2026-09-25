"""Transactional outbox + background delivery: turn write + cross-layer events
in one atomic transaction, crash-replayable.

The outbox lives in ``sprout_conversation.db``; on every ``append_turn`` an event is
inserted in the same transaction, so a crash can never leave a turn without
its memory-index / observation / trajectory counterparts. A worker drains the
outbox, idempotent on ``event_id``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from Sprout.events import OUTBOX_OBSERVATION, OUTBOX_TURN_INDEXED
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.turns import _APPEND_SQL, turn_append_parameters

logger = logging.getLogger("sprout.memory.outbox")

if TYPE_CHECKING:
    from Sprout.memory.contract import SessionSearch
    from Sprout.session.models import Turn
    from Sprout.storage.contracts.observations import ObservationStore

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    session_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(delivered_at);
"""


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    kind: str
    session_id: str
    payload: dict


def migrate_outbox(db: SqliteDatabase) -> None:
    db.executescript(OUTBOX_SCHEMA)


async def append_turn_with_outbox(
    db: SqliteDatabase,
    turn: Turn,
    *,
    body_for_index: str | None = None,
    extra_events: Iterable[tuple[str, dict]] = (),
) -> None:
    """Write a turn and one or more outbox events in a single transaction.

    ``body_for_index`` is what the memory index should index; pass a preview
    for offloaded turns so FTS still has something to search over.
    """
    index_payload: dict = {
        "turn_id": turn.id,
        "role": turn.role,
        "seq": turn.seq,
        "body": body_for_index if body_for_index is not None else turn.content,
    }
    events = [
        OutboxEvent(
            event_id=str(uuid4()),
            kind=OUTBOX_TURN_INDEXED,
            session_id=turn.session_id,
            payload=index_payload,
        )
    ]
    events.extend(
        OutboxEvent(
            event_id=str(uuid4()),
            kind=kind,
            session_id=turn.session_id,
            payload=dict(payload),
        )
        for kind, payload in extra_events
    )
    statements = [
        (_APPEND_SQL, turn_append_parameters(turn))
    ]
    now = datetime.now(UTC).isoformat()
    for event in events:
        statements.append(
            (
                "INSERT INTO outbox (event_id, kind, session_id, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.kind,
                    event.session_id,
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                    now,
                ),
            )
        )
    for attempt in range(3):
        try:
            await db.execute_batch(statements)
            return
        except sqlite3.IntegrityError:
            if attempt == 2:
                raise


class OutboxWorker:
    """Drains the outbox idempotently."""

    def __init__(
        self,
        *,
        db: SqliteDatabase,
        session_search: SessionSearch | None = None,
        observations: ObservationStore | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        self._db = db
        self._session_search = session_search
        self._observations = observations
        self._poll = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        # Final flush: a turn appended after the last poll tick would
        # otherwise stay pending until the next process start.
        try:
            await self.drain_once(limit=50)
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                drained = await self.drain_once(limit=50)
            except Exception:  # noqa: BLE001 - worker must not crash
                drained = 0
            if drained == 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
                except TimeoutError:
                    pass

    async def drain_once(self, *, limit: int = 50) -> int:
        """Deliver pending events; returns the number that actually landed.

        A failure leaves the row pending for the next pass, which is correct —
        the outbox exists so a crash cannot lose the derived write. What was not
        correct is that it did so *silently and while counting the event as
        delivered*: the caller saw progress, nothing was logged, and an event
        that could never succeed (a malformed payload, a schema mismatch in the
        derived lane) retried forever with no trace. Failures are now logged and
        kept out of the count, so ``0`` means "nothing got through" rather than
        "nothing was attempted".
        """
        rows = await self._db.fetchall(
            "SELECT * FROM outbox WHERE delivered_at IS NULL "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        delivered = 0
        for row in rows:
            event = OutboxEvent(
                event_id=row["event_id"],
                kind=row["kind"],
                session_id=row["session_id"],
                payload=json.loads(row["payload_json"]),
            )
            try:
                await self._handle(event)
                await self._db.execute(
                    "UPDATE outbox SET delivered_at = ? WHERE event_id = ?",
                    (datetime.now(UTC).isoformat(), event.event_id),
                )
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - leave event for the next pass
                logger.warning(
                    "Outbox event %s (%s) for session %s failed and stays "
                    "pending: %s: %s",
                    event.event_id,
                    event.kind,
                    event.session_id,
                    type(exc).__name__,
                    exc,
                )
        return delivered

    async def pending_count(self) -> int:
        """How many events are still undelivered.

        A queue that never drains looks identical to an idle one from the
        outside; this is the number that tells them apart.
        """
        return int(
            await self._db.scalar(
                "SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL"
            )
            or 0
        )

    async def _handle(self, event: OutboxEvent) -> None:
        if event.kind == OUTBOX_TURN_INDEXED and self._session_search is not None:
            payload = event.payload
            await self._session_search.index_turn(
                session_id=event.session_id,
                turn_id=payload["turn_id"],
                turn_seq=int(payload.get("seq", 0)),
                role=payload.get("role", ""),
                body=payload.get("body", ""),
            )
        elif event.kind == OUTBOX_OBSERVATION and self._observations is not None:
            payload = event.payload
            from Sprout.events.event import Event

            await self._observations.append_event(
                Event(
                    name=payload.get("name", event.kind),
                    payload=payload,
                    correlation_id=payload.get("correlation_id"),
                )
            )


__all__ = [
    "OutboxEvent",
    "OutboxWorker",
    "append_turn_with_outbox",
    "migrate_outbox",
]

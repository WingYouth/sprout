"""Blobstore session store: session documents live in the blob store.

Each session and turn is serialized as a JSON document and written through the
:class:`~Sprout.storage.contracts.blobs.BlobStore` contract (content-addressed,
deduplicated). A small ``index.json`` beside the blobs maps ids to blob URIs
and is rewritten atomically on every save; the payloads — the bulk of the
data — remain plain blobs that any blob backend can serve.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from Sprout.rootstock.contract import (
    blob_uris_in,
    turn_from_document,
    turn_to_document,
)
from Sprout.session.models import Session, Turn
from Sprout.storage.contracts.blobs import BlobStore

_INDEX_NAME = "index.json"


def _session_document(session: Session) -> dict[str, Any]:
    return {
        "kind": "session",
        "id": session.id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat(),
        "metadata": session.metadata,
    }


def _turn_document(turn: Turn) -> dict[str, Any]:
    return turn_to_document(turn)


def _write_index_sync(path: Path, index: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(index, ensure_ascii=False, default=str), encoding="utf-8"
    )
    os.replace(tmp, path)


class BlobSessionStore:
    """Sessions and turns as JSON blobs plus a local id→uri index."""

    def __init__(self, root: str | Path, blobs: BlobStore) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._blobs = blobs
        self._index_path = self._root / _INDEX_NAME
        self._index: dict[str, Any] = self._load_index()
        self._reserve_index()

    def _reserve_index(self) -> None:
        """Create ``index.json`` on open so the backend is reserved like SQLite."""
        if not self._index_path.exists():
            _write_index_sync(self._index_path, self._index)

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.exists():
            return {"sessions": {}, "turns": {}, "seq_high_water": {}}
        data = json.loads(self._index_path.read_text(encoding="utf-8"))
        return {
            "sessions": data.get("sessions", {}),
            "turns": data.get("turns", {}),
            # Per-session monotonic ``seq`` high-water marks, persisted so
            # post-restart appends keep the sequence going.
            "seq_high_water": data.get("seq_high_water", {}),
        }

    async def _save_index(self) -> None:
        await asyncio.to_thread(_write_index_sync, self._index_path, self._index)

    async def _put_document(self, document: dict[str, Any]) -> str:
        payload = json.dumps(document, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
        return await self._blobs.put(payload, mime_type="application/json")

    async def _get_document(self, uri: str) -> dict[str, Any]:
        return json.loads((await self._blobs.get(uri)).decode("utf-8"))

    async def get_session(self, session_id: str) -> Session | None:
        uri = self._index["sessions"].get(session_id)
        if uri is None:
            return None
        document = await self._get_document(uri)
        return Session(
            id=document["id"],
            user_id=document["user_id"],
            created_at=datetime.fromisoformat(document["created_at"]),
            metadata=document.get("metadata", {}),
        )

    async def save_session(self, session: Session) -> None:
        uri = await self._put_document(_session_document(session))
        self._index["sessions"][session.id] = uri
        await self._save_index()

    async def append_turn(self, turn: Turn) -> None:
        # Assign a per-session monotonic seq when the caller did not, matching
        # the SQLite and in-memory backends' ordering guarantees.
        if turn.seq <= 0:
            high_water = self._index["seq_high_water"]
            turn = replace(turn, seq=high_water.get(turn.session_id, 0) + 1)
        high_water = self._index["seq_high_water"]
        high_water[turn.session_id] = max(turn.seq, high_water.get(turn.session_id, 0))
        uri = await self._put_document(_turn_document(turn))
        self._index["turns"][turn.id] = uri
        await self._save_index()

    async def _load_session_turns(self, session_id: str) -> list[Turn]:
        """Materialize every turn of one session from its blob documents."""
        turns: list[Turn] = []
        for turn_id, uri in self._index["turns"].items():
            document = await self._get_document(uri)
            if document["session_id"] != session_id:
                continue
            # ``turn_from_document`` reads every authority field, so a turn
            # written before those columns existed still loads (each falls back
            # to its dataclass default), and one written now keeps them.
            turns.append(turn_from_document({**document, "id": turn_id}))
        turns.sort(key=lambda turn: (turn.seq, turn.created_at))
        return turns

    async def recent_turns(
        self, session_id: str, limit: int = 20
    ) -> Sequence[Turn]:
        return (await self._load_session_turns(session_id))[-limit:]

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> Sequence[Turn]:
        """Up to ``limit`` turns with ``seq`` below ``seq``, oldest first (keyset)."""
        older = [
            turn
            for turn in await self._load_session_turns(session_id)
            if turn.seq < seq
        ]
        return older[-limit:]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(await self._load_session_turns(session_id))

    async def delete_session(self, session_id: str) -> int:
        """Drop the session and every turn; returns the number of turns dropped.

        The blob payloads themselves stay put: they are content-addressed and
        reclaimed by the blob store's garbage collection, not by the session
        layer. Only the index entries are removed here.
        """
        doomed: set[str] = set()
        for turn_id, uri in self._index["turns"].items():
            document = await self._get_document(uri)
            if document["session_id"] == session_id:
                doomed.add(turn_id)
        for turn_id in doomed:
            del self._index["turns"][turn_id]
        self._index["sessions"].pop(session_id, None)
        self._index["seq_high_water"].pop(session_id, None)
        await self._save_index()
        return len(doomed)

    async def count_sessions(self) -> int:
        return len(self._index["sessions"])

    async def count_turns(self) -> int:
        return len(self._index["turns"])

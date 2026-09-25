"""Redis session backend: the hot-cache lane behind the SessionStore protocol.

Each session is a hash at ``sprout:session:{id}`` with its turn list at
``sprout:session:{id}:turns`` (RPUSH/LRANGE) and a per-session sequence
counter at ``sprout:session:{id}:seq``. Both keys carry a TTL so the lane
self-trims, and the turn list is capped at :data:`MAX_CACHED_TURNS` entries.

Redis is a *derived* lane in the data-layer plan (authority is false): a
RedisSessionStore can stand alone, but its intended role is the hot cache in
front of a durable backend, reachable through
:class:`~Sprout.storage.lanes.SixLaneFanout`. Requires the ``redis`` package
and a reachable server (``redis://host:6379``).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from typing import Any

from Sprout.rootstock.contract import blob_uris_in
from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.session.models import Session, Turn

KEY_PREFIX = "sprout:session:"
SESSION_TTL_SECONDS = 86400
MAX_CACHED_TURNS = 1000

#: Registry of live sessions; members whose hash expired are pruned on read.
INDEX_KEY = "sprout:sessions"


def session_key(session_id: str) -> str:
    """The hash key holding session metadata."""
    return f"{KEY_PREFIX}{session_id}"


def turns_key(session_id: str) -> str:
    """The list key holding the session's turns."""
    return f"{KEY_PREFIX}{session_id}:turns"


def seq_key(session_id: str) -> str:
    """The counter key assigning the per-session monotonic turn sequence."""
    return f"{KEY_PREFIX}{session_id}:seq"


def _session_to_hash(session: Session) -> dict[str, str]:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat(),
        "metadata_json": json.dumps(session.metadata, ensure_ascii=False, default=str),
    }


def _turn_to_json(turn: Turn) -> str:
    return json.dumps(
        {
            "id": turn.id,
            "session_id": turn.session_id,
            "role": turn.role,
            "content": turn.content,
            "created_at": turn.created_at.isoformat(),
            "seq": turn.seq,
            "metadata": turn.metadata,
        },
        ensure_ascii=False,
    )


def _json_to_turn(raw: str) -> Turn:
    data: dict[str, Any] = json.loads(raw)
    return Turn(
        session_id=data["session_id"],
        role=data["role"],
        content=data["content"],
        id=data["id"],
        created_at=datetime.fromisoformat(data["created_at"]),
        seq=int(data["seq"]),
        metadata=data.get("metadata", {}),
    )


class RedisSessionStore:
    """Sessions and turns in Redis hashes and lists, TTL-scoped."""

    backend_name = "redis"

    def __init__(self, dsn: str, *, ttl: int = SESSION_TTL_SECONDS) -> None:
        if importlib.util.find_spec("redis") is None:
            raise RootstockUnavailableError(
                "The redis session backend requires the 'redis' package. "
                f"Install it (e.g. `uv add redis`) and keep [storage] session = "
                f'"{dsn}".'
            )
        from redis.asyncio import Redis

        self.dsn = dsn
        self.ttl = ttl
        self._redis = Redis.from_url(dsn, decode_responses=True)

    @property
    def redis(self):
        """The underlying asyncio client (for lane-level cache operations)."""
        return self._redis

    async def close(self) -> None:
        await self._redis.aclose()

    async def _expire(self, session_id: str) -> None:
        await self._redis.expire(session_key(session_id), self.ttl)
        await self._redis.expire(turns_key(session_id), self.ttl)
        await self._redis.expire(seq_key(session_id), self.ttl)

    async def get_session(self, session_id: str) -> Session | None:
        data = await self._redis.hgetall(session_key(session_id))
        if not data:
            return None
        return Session(
            id=data["id"],
            user_id=data["user_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=json.loads(data.get("metadata_json") or "{}"),
        )

    async def save_session(self, session: Session) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(session_key(session.id), mapping=_session_to_hash(session))
            pipe.sadd(INDEX_KEY, session.id)
            pipe.expire(session_key(session.id), self.ttl)
            await pipe.execute()

    async def append_turn(self, turn: Turn) -> None:
        # ``turn.seq`` is honored when nonzero: the six-lane fan-out passes the
        # authority-assigned sequence so the cache lane mirrors it exactly.
        if turn.seq > 0:
            seq = turn.seq
            await self._redis.set(seq_key(turn.session_id), seq)
        else:
            seq = await self._redis.incr(seq_key(turn.session_id))
        stored = Turn(
            session_id=turn.session_id,
            role=turn.role,
            content=turn.content,
            id=turn.id,
            created_at=turn.created_at,
            seq=seq,
            metadata=turn.metadata,
        )
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(turns_key(turn.session_id), _turn_to_json(stored))
            pipe.ltrim(turns_key(turn.session_id), -MAX_CACHED_TURNS, -1)
            pipe.sadd(INDEX_KEY, turn.session_id)
            pipe.expire(turns_key(turn.session_id), self.ttl)
            pipe.expire(seq_key(turn.session_id), self.ttl)
            await pipe.execute()

    async def recent_turns(self, session_id: str, limit: int = 20) -> list[Turn]:
        # RPUSH keeps the list chronological, so the tail slice is already
        # oldest -> newest, matching the other backends' ordering contract.
        raw = await self._redis.lrange(turns_key(session_id), -limit, -1)
        return [_json_to_turn(entry) for entry in raw]

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> list[Turn]:
        """Turns with ``seq`` below the given one, oldest first (keyset paging)."""
        raw = await self._redis.lrange(turns_key(session_id), 0, -1)
        turns = [
            _json_to_turn(entry)
            for entry in raw
            if _json_to_turn(entry).seq < seq
        ]
        turns.sort(key=lambda turn: turn.seq)
        return turns[:limit]

    async def session_blob_uris(self, session_id: str) -> list[str]:
        """Blob URIs this session's turns reference (see the contract)."""
        return blob_uris_in(
            await self.turns_before(session_id, seq=10**12, limit=10**6)
        )

    async def delete_session(self, session_id: str) -> int:
        dropped = await self._redis.llen(turns_key(session_id))
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(
                session_key(session_id),
                turns_key(session_id),
                seq_key(session_id),
            )
            pipe.srem(INDEX_KEY, session_id)
            await pipe.execute()
        return int(dropped)

    async def count_sessions(self) -> int:
        """Best-effort: members of the index whose session hash still exists."""
        members = await self._redis.smembers(INDEX_KEY)
        live = 0
        for member in members:
            if await self._redis.exists(session_key(member)):
                live += 1
            else:
                await self._redis.srem(INDEX_KEY, member)
        return live

    async def count_turns(self) -> int:
        """Best-effort: sum of live turn lists (cache lane semantics)."""
        members = await self._redis.smembers(INDEX_KEY)
        total = 0
        for member in members:
            total += await self._redis.llen(turns_key(member))
        return int(total)


__all__ = [
    "INDEX_KEY",
    "KEY_PREFIX",
    "MAX_CACHED_TURNS",
    "SESSION_TTL_SECONDS",
    "RedisSessionStore",
    "seq_key",
    "session_key",
    "turns_key",
]

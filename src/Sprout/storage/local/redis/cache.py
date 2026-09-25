"""Redis cache lane: the CacheStore contract over a real Redis server."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from Sprout.rootstock.errors import RootstockUnavailableError


def _require_redis(dsn: str) -> None:
    if importlib.util.find_spec("redis") is None:
        raise RootstockUnavailableError(
            "The redis cache lane requires the 'redis' package. "
            f"Install it (e.g. `uv add redis`) and set [storage] cache = \"{dsn}\"."
        )


class RedisCacheStore:
    """JSON-serialized cache entries with optional per-key TTL."""

    def __init__(self, dsn: str) -> None:
        _require_redis(dsn)
        from redis.asyncio import Redis

        self.dsn = dsn
        self._redis = Redis.from_url(dsn, decode_responses=True)

    @property
    def redis(self):
        return self._redis

    async def close(self) -> None:
        await self._redis.aclose()

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        if ttl_seconds is None:
            await self._redis.set(key, payload)
        else:
            await self._redis.set(key, payload, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)


__all__ = ["RedisCacheStore"]

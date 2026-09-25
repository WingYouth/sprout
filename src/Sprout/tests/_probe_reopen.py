"""Do Turn authority fields survive a store reopen (journal replay)?"""
import asyncio
from pathlib import Path

from Sprout.session.models import Turn

FIELDS = ("content_type", "content_blob_uri", "line_count", "token_estimate", "language")

def make():
    return Turn(session_id="s1", role="user", content="body", seq=1,
        content_type="folded_block", content_blob_uri="blob-abc",
        line_count=7, token_estimate=42, language="zh")

def test_reopen(tmp_path: Path) -> None:
    async def main():
        from Sprout.rootstock.backends.blob_store import BlobSessionStore
        from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
        from Sprout.storage.local.memory import MemoryBlobStore

        p = str(tmp_path / "s.jsonl")
        s = JsonlSessionStore(p)
        await s.append_turn(make())
        s2 = JsonlSessionStore(p)          # reopen -> replay
        got = (await s2.recent_turns("s1", limit=5))[0]
        lost = [f for f in FIELDS if getattr(got, f) != getattr(make(), f)]
        print(f"  jsonl after reopen      lost={lost or 'NONE'}")
        print(f"  jsonl blob uris         {await s2.session_blob_uris('s1')}")

        b = BlobSessionStore(str(tmp_path / "blobs"), MemoryBlobStore())
        await b.append_turn(make())
        got = (await b.recent_turns("s1", limit=5))[0]
        lost = [f for f in FIELDS if getattr(got, f) != getattr(make(), f)]
        print(f"  blobstore               lost={lost or 'NONE'}")
        collector = getattr(b, "session_blob_uris", None)
        uris = await collector("s1") if collector else "METHOD MISSING"
        print(f"  blobstore blob uris     {uris}")

        try:
            from Sprout.rootstock.backends.neo4j_store import Neo4jSessionStore
            n = Neo4jSessionStore("neo4j://x")
            print("  neo4j                   has method:", hasattr(n, "session_blob_uris"))
        except Exception as e:
            print(f"  neo4j unavailable: {type(e).__name__}")
        try:
            from Sprout.rootstock.backends.redis_store import RedisSessionStore
            r = RedisSessionStore("redis://x")
            print("  redis                   has method:", hasattr(r, "session_blob_uris"))
        except Exception as e:
            print(f"  redis unavailable: {type(e).__name__}")
        from Sprout.storage.lanes import SixLaneFanout
        f = SixLaneFanout(s2)
        print("  SixLaneFanout           has method:", hasattr(f, "session_blob_uris"))
    asyncio.run(main())

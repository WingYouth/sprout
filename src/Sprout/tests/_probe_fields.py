"""Which backends preserve every Turn authority field through a round-trip?"""
import asyncio
from pathlib import Path

from Sprout.session.models import Turn

FIELDS = ("content_type", "content_blob_uri", "line_count", "token_estimate", "language")

def make() -> Turn:
    return Turn(
        session_id="s1", role="user", content="body", seq=1,
        content_type="folded_block", content_blob_uri="blob-abc",
        line_count=7, token_estimate=42, language="zh",
    )

async def check(store, label):
    await store.append_turn(make())
    turns = await store.recent_turns("s1", limit=5)
    got = turns[0]
    lost = [f for f in FIELDS if getattr(got, f) != getattr(make(), f)]
    print(f"  {label:20} lost={lost if lost else 'NONE'}")

def test_probe(tmp_path: Path) -> None:
    async def main():
        from Sprout.rootstock.backends.blob_store import BlobSessionStore
        from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
        from Sprout.rootstock.backends.memory_store import MemorySessionStore
        from Sprout.storage.local.memory import MemoryBlobStore

        await check(MemorySessionStore(), "memory_store")
        await check(JsonlSessionStore(str(tmp_path / "s.jsonl")), "jsonl_store")
        await check(
            BlobSessionStore(str(tmp_path / "blobs"), MemoryBlobStore()),
            "blob_store",
        )
    asyncio.run(main())

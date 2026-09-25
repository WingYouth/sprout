"""Cascade cleanup must remove offloaded bodies whatever session backend is used.

An oversized turn body is offloaded to the blob store and no longer lives in
``Turn.content``. Its URI is content-addressed — a bare hash filename with no
session component — so the turns are the *only* record of which blob belongs to
which session. ``delete_session_cascade`` therefore has to read the URIs off the
turns before deleting them, and it asks the session store for them via
``session_blob_uris``.

The URI can be recorded in two places, and both must be checked: the
``content_blob_uri`` column, and the ``blob_uri`` envelope key that
``Runtime._offload_body`` actually writes (see ``rootstock.contract.blob_uri_of``).
Reading only the column meant every body the runtime offloaded was invisible to
the cascade, so the delete loop ran zero times and the report still said
``blobs: 0``.

Nothing reclaims them later: ``BlobStore`` is put/get/exists/delete/count with no
garbage collection, despite ``blob_store.py``'s docstring calling the payloads
"reclaimed by the blob store's garbage collection".
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from Sprout.rootstock.backends.memory_store import MemorySessionStore
from Sprout.session.models import Session, Turn
from Sprout.storage.bundle import StorageBundle
from Sprout.storage.contracts.blobs import BlobStore


class _RecordingBlobs:
    """A blob store that records deletes, so a leak is visible."""

    def __init__(self) -> None:
        self.stored: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, data: bytes, *, mime_type: str) -> str:
        uri = f"blob-{len(self.stored)}"
        self.stored[uri] = data
        return uri

    async def get(self, uri: str) -> bytes:
        return self.stored[uri]

    async def exists(self, uri: str) -> bool:
        return uri in self.stored

    async def delete(self, uri: str) -> bool:
        if uri not in self.stored:
            return False
        self.deleted.append(uri)
        del self.stored[uri]
        return True

    async def count(self) -> int:
        return len(self.stored)


async def _seed_session(store: MemorySessionStore, session_id: str, uri: str) -> None:
    """A session with one ordinary turn and one offloaded the way the runtime does.

    Uses the envelope form (``{"blob_uri": ...}``), not ``content_blob_uri``:
    ``Runtime._offload_body`` rewrites the envelope, so that is what a real
    offload looks like in the store.
    """
    await store.save_session(Session(id=session_id, user_id="u", channel="cli"))
    await store.append_turn(
        Turn(session_id=session_id, seq=1, role="user", content="hi")
    )
    await store.append_turn(
        Turn(
            session_id=session_id,
            seq=2,
            role="user",
            content="preview...",
            metadata={"blob_uri": uri, "content_bytes": 999999},
        )
    )


async def test_blob_is_removed_on_the_memory_backend(tmp_path: Path) -> None:
    """The default test backend — the case the sqlite-only method misses."""
    store = MemorySessionStore()
    blobs = _RecordingBlobs()
    uri = await blobs.put(b"x" * 10, mime_type="text/plain")
    await _seed_session(store, "s1", uri)

    bundle = replace(StorageBundle.in_memory(), blobs=blobs, sessions=store)
    report = await bundle.delete_session_cascade("s1")

    assert blobs.deleted == [uri], "the offloaded body leaked"
    assert report["blobs"] == 1
    assert await blobs.exists(uri) is False


async def test_every_backend_can_report_its_blob_uris(tmp_path: Path) -> None:
    """The probe in ``delete_session_cascade`` must not be backend-dependent.

    ``getattr(store, "session_blob_uris", None)`` hides a missing method behind
    a silent ``None``, which reads as "this session has no blobs" rather than
    "this backend cannot answer".
    """
    from Sprout.rootstock.backends.blob_store import BlobSessionStore
    from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore
    from Sprout.rootstock.backends.memory_store import MemorySessionStore
    from Sprout.storage.lanes import SixLaneFanout
    from Sprout.storage.local.memory import MemoryBlobStore

    authority = MemorySessionStore()
    stores = [
        authority,
        JsonlSessionStore(str(tmp_path / "s.jsonl")),
        BlobSessionStore(str(tmp_path / "blobs"), MemoryBlobStore()),
        # The fan-out is what ``sessions`` points at whenever the six lanes are
        # wired, i.e. on exactly the deployments that own a blobstore.
        SixLaneFanout(authority),
    ]
    for store in stores:
        assert hasattr(store, "session_blob_uris"), (
            f"{type(store).__name__} cannot report blob URIs, so cascade "
            "cleanup leaks every offloaded body on this backend"
        )


async def test_a_fanout_forwards_blob_uris_from_its_authority(tmp_path: Path) -> None:
    """The wrapper must delegate, not answer "no blobs" on the authority's behalf."""
    from Sprout.storage.lanes import SixLaneFanout

    authority = MemorySessionStore()
    await authority.append_turn(
        Turn(
            session_id="s1",
            role="user",
            content="preview...",
            metadata={"blob_uri": "blob-via-fanout"},
        )
    )

    assert await SixLaneFanout(authority).session_blob_uris("s1") == ["blob-via-fanout"]


async def test_the_envelope_uri_is_found_whatever_the_backend(tmp_path: Path) -> None:
    """Each backend must see the URI the runtime actually writes.

    The runtime offloads a body by rewriting the *envelope*, so a store that
    only inspects ``Turn.content_blob_uri`` reports nothing for every real
    offload.
    """
    from Sprout.rootstock.backends.jsonl_store import JsonlSessionStore

    for store in (
        MemorySessionStore(),
        JsonlSessionStore(str(tmp_path / "s.jsonl")),
    ):
        await store.save_session(Session(id="s1", user_id="u", channel="cli"))
        await store.append_turn(
            Turn(
                session_id="s1",
                role="user",
                content="preview...",
                metadata={"blob_uri": "blob-envelope-uri", "content_bytes": 999999},
            )
        )
        assert await store.session_blob_uris("s1") == ["blob-envelope-uri"], (
            f"{type(store).__name__} missed the envelope-encoded blob URI"
        )


async def test_the_column_uri_is_still_found(tmp_path: Path) -> None:
    """The column form must keep working — it is a supported place to record this."""
    store = MemorySessionStore()
    await store.save_session(Session(id="s1", user_id="u", channel="cli"))
    await store.append_turn(
        Turn(session_id="s1", role="user", content="c", content_blob_uri="blob-column-uri")
    )

    assert await store.session_blob_uris("s1") == ["blob-column-uri"]


async def test_blob_store_has_no_garbage_collection(tmp_path: Path) -> None:
    """Why a leak is permanent: nothing else ever reclaims an orphan blob.

    ``blob_store.py`` claims the payloads are "reclaimed by the blob store's
    garbage collection", but the contract has no such operation, so a blob
    missed by the cascade is missed forever.
    """
    from Sprout.storage.local.filesystem.blobs import FileBlobStore

    store = FileBlobStore(tmp_path / "blobs")
    api = {name for name in dir(store) if not name.startswith("_")}
    assert not (api & {"gc", "collect", "sweep", "prune", "collect_garbage"}), (
        "a GC appeared; the leak may no longer be permanent and this test "
        "should be revisited"
    )
    assert set(BlobStore.__protocol_attrs__) <= {"put", "get", "exists", "delete", "count"}

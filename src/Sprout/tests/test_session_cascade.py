"""``delete_session_cascade`` must drop *all* of a session's derived data.

Regression: three separate leaks on the delete path.

* ``bundle.py`` guarded blob cleanup behind ``getattr(self.blobs, "list", None)``,
  but ``FileBlobStore`` has no ``list`` method — so the ``blobs`` count was
  structurally always 0 and every offloaded turn body stayed on disk forever.
* ``SqliteSessionStore.delete_session`` deleted only ``turns`` and ``sessions``,
  so ``attachments`` and ``message_task_link`` rows accumulated for sessions
  that no longer existed.
"""

from __future__ import annotations

import pytest

from Sprout.message.attachment import Attachment
from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.session.models import Session, Turn
from Sprout.storage.local.filesystem.blobs import FileBlobStore
from Sprout.storage.local.sqlite.driver import SqliteDatabase


def _store(tmp_path) -> SqliteSessionStore:
    return SqliteSessionStore(SqliteDatabase(str(tmp_path / "conv.db")))


def _count(store: SqliteSessionStore, table: str) -> int:
    return len(store._db.fetchall_sync(f"SELECT 1 FROM {table}"))


@pytest.mark.asyncio
async def test_delete_session_drops_attachments_and_task_links(tmp_path) -> None:
    """Attachments and message↔task edges are per-session derived rows."""
    store = _store(tmp_path)
    await store.save_session(Session(id="s1", user_id="u1"))
    turn = Turn("s1", "user", "hello")
    await store.append_turn(turn)
    await store.save_attachment(
        Attachment(filename="a.pdf", mime_type="application/pdf", size=10),
        message_id=turn.id,
    )
    await store.link_message_task(turn.id, "task-1")

    assert _count(store, "attachments") == 1
    assert _count(store, "message_task_link") == 1

    await store.delete_session("s1")

    assert _count(store, "attachments") == 0, (
        "attachment rows survived their session's deletion"
    )
    assert _count(store, "message_task_link") == 0, (
        "message_task_link rows survived their session's deletion"
    )


@pytest.mark.asyncio
async def test_delete_session_leaves_other_sessions_intact(tmp_path) -> None:
    store = _store(tmp_path)
    for sid in ("s1", "s2"):
        await store.save_session(Session(id=sid, user_id="u1"))
        turn = Turn(sid, "user", f"hello from {sid}")
        await store.append_turn(turn)
        await store.save_attachment(
            Attachment(filename=f"{sid}.pdf", mime_type="application/pdf", size=1),
            message_id=turn.id,
        )

    await store.delete_session("s1")

    assert _count(store, "attachments") == 1


@pytest.mark.asyncio
async def test_blob_store_lists_and_deletes_by_uri(tmp_path) -> None:
    """The cascade needs a way to enumerate blobs; FileBlobStore had none.

    Offloaded bodies are content-addressed (the URI is a bare hash filename),
    so the delete path must resolve URIs from the turns' envelopes rather than
    guess a ``turns/<session_id>/`` prefix.
    """
    blobs = FileBlobStore(tmp_path / "media")
    uri = await blobs.put(b"x" * 32, mime_type="text/plain")
    assert await blobs.count() == 1

    assert await blobs.delete(uri) is True
    assert await blobs.count() == 0


@pytest.mark.asyncio
async def test_cascade_removes_offloaded_blobs(tmp_path) -> None:
    """A deleted session must take its offloaded turn bodies with it.

    Uses the real ``FileBlobStore`` (which has no ``list``) and a real SQLite
    session store, because the defect was specific to those implementations.
    """
    from dataclasses import replace

    from Sprout.storage.bundle import StorageBundle

    blobs = FileBlobStore(tmp_path / "media")
    store = _store(tmp_path)
    bundle = replace(StorageBundle.in_memory(), sessions=store, blobs=blobs)

    await store.save_session(Session(id="s1", user_id="u1"))
    uri = await blobs.put(b"y" * 4096, mime_type="text/plain")
    turn = replace(Turn("s1", "user", "[truncated]"), content_blob_uri=uri)
    await store.append_turn(turn)
    assert await blobs.count() == 1

    report = await bundle.delete_session_cascade("s1")

    assert report["blobs"] == 1, "the offloaded body was left on disk"
    assert await blobs.count() == 0


@pytest.mark.asyncio
async def test_cascade_removes_blobs_offloaded_by_the_runtime(tmp_path) -> None:
    """The envelope form, which is the one the runtime actually writes.

    ``Runtime._offload_body`` records the URI under the ``blob_uri`` envelope
    key and leaves ``Turn.content_blob_uri`` unset. The cascade used to read the
    column only, so on every real offload it collected nothing, deleted nothing,
    and still reported ``blobs: 0`` — a silent leak into a store that has no
    garbage collection to catch it. The test above passes a column-form turn,
    which is why the suite stayed green through the leak.
    """
    from dataclasses import replace

    from Sprout.storage.bundle import StorageBundle

    blobs = FileBlobStore(tmp_path / "media")
    store = _store(tmp_path)
    bundle = replace(StorageBundle.in_memory(), sessions=store, blobs=blobs)

    await store.save_session(Session(id="s1", user_id="u1"))
    uri = await blobs.put(b"z" * 4096, mime_type="text/plain")
    # Exactly what the runtime persists for an oversized body: a preview plus
    # the envelope, and no column value.
    await store.append_turn(
        Turn(
            "s1",
            "user",
            "[truncated]",
            metadata={"blob_uri": uri, "content_bytes": 999999},
        )
    )

    report = await bundle.delete_session_cascade("s1")

    assert report["blobs"] == 1, "the runtime-offloaded body leaked"
    assert await blobs.count() == 0


@pytest.mark.asyncio
async def test_cascade_removes_context_snapshot_blobs(tmp_path) -> None:
    """The context lane offloads its own bodies; they must be reclaimed too.

    ``SixLaneFanout.persist_context`` writes bodies over its threshold to the
    blobstore and records the URI on ``ContextRecord.blob_uri`` — not on any
    turn, so the turn scan could never see them.
    """
    from dataclasses import replace

    from Sprout.storage.bundle import StorageBundle
    from Sprout.storage.contracts.context import ContextRecord
    from Sprout.storage.local.sqlite.context import SqliteContextStore

    blobs = FileBlobStore(tmp_path / "media")
    context = SqliteContextStore(SqliteDatabase(str(tmp_path / "context.db")))
    bundle = replace(
        StorageBundle.in_memory(),
        sessions=_store(tmp_path),
        blobs=blobs,
        context=context,
    )

    uri = await blobs.put(b"c" * 70000, mime_type="text/markdown")
    await context.append(
        ContextRecord(session_id="s1", snapshot_hash="h", text="t", blob_uri=uri)
    )

    report = await bundle.delete_session_cascade("s1")

    assert await blobs.count() == 0, "the offloaded context snapshot leaked"
    assert report["blobs"] == 1


@pytest.mark.asyncio
async def test_a_blob_shared_by_two_turns_is_deleted_once(tmp_path) -> None:
    """De-duplication: a repeated URI must not be counted (or deleted) twice."""
    from dataclasses import replace

    from Sprout.storage.bundle import StorageBundle

    blobs = FileBlobStore(tmp_path / "media")
    store = _store(tmp_path)
    bundle = replace(StorageBundle.in_memory(), sessions=store, blobs=blobs)

    uri = await blobs.put(b"s" * 64, mime_type="text/plain")
    for seq in (1, 2):
        await store.append_turn(
            Turn("s1", "user", f"preview {seq}", seq=seq, metadata={"blob_uri": uri})
        )

    report = await bundle.delete_session_cascade("s1")

    assert report["blobs"] == 1
    assert await blobs.count() == 0

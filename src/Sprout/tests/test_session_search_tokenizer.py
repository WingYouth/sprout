"""``SqliteSessionSearch`` must report the tokenizer its table actually has.

Regression: ``_open_fts`` tried the trigram schema first and treated a
non-raising call as success. But the table is created earlier by
``SqliteSessionStore`` (``tokenize='unicode61'``), and ``CREATE VIRTUAL TABLE
IF NOT EXISTS`` against an existing table is a silent no-op — so the object
reported ``tokenizer == "trigram"`` while ``sqlite_master`` said ``unicode61``,
and ``sprout storage status`` printed the wrong one.

The practical impact is CJK search: ``unicode61`` treats a whole Chinese
sentence as one token, so sub-phrase queries match nothing, while ``trigram``
matches them.
"""

from __future__ import annotations

import pytest

from Sprout.memory.backends.session_search import SqliteSessionSearch
from Sprout.rootstock.backends.sqlite_store import SqliteSessionStore
from Sprout.storage.local.sqlite.driver import SqliteDatabase


def _actual_tokenizer(db: SqliteDatabase) -> str:
    rows = db.fetchall_sync(
        "SELECT sql FROM sqlite_master WHERE name = 'turns_fts'"
    )
    assert rows, "turns_fts was never created"
    return rows[0]["sql"]


def test_reported_tokenizer_matches_the_table(tmp_path) -> None:
    """The attribute must describe reality, not the schema that was attempted."""
    db = SqliteDatabase(str(tmp_path / "conv.db"))
    SqliteSessionStore(db)  # turns_fts is created here, not by the search layer
    search = SqliteSessionSearch(db)

    actual = _actual_tokenizer(db)
    assert search.tokenizer in actual, (
        f"reported {search.tokenizer!r} but the table is {actual!r}"
    )


def test_tokenizer_is_never_misreported_as_trigram_for_a_unicode61_table(
    tmp_path,
) -> None:
    db = SqliteDatabase(str(tmp_path / "conv.db"))
    SqliteSessionStore(db)
    search = SqliteSessionSearch(db)

    if "trigram" not in _actual_tokenizer(db):
        assert search.tokenizer != "trigram", (
            "reported trigram for a table that is not trigram — the IF NOT "
            "EXISTS no-op was mistaken for success"
        )


@pytest.mark.asyncio
async def test_cjk_substring_search_finds_a_stored_turn(tmp_path) -> None:
    """Search must work for CJK text, which is why trigram was wanted."""
    from Sprout.session.models import Session, Turn

    db = SqliteDatabase(str(tmp_path / "conv.db"))
    store = SqliteSessionStore(db)
    search = SqliteSessionSearch(db)

    await store.save_session(Session(id="s1", user_id="u1"))
    turn = Turn("s1", "user", "项目分析与存储层设计")
    await store.append_turn(turn)
    await search.index_turn(
        session_id="s1", turn_id=turn.id, turn_seq=1, role="user", body=turn.content
    )

    hits = await search.search("存储层", limit=5)

    assert hits, (
        "CJK sub-phrase search returned nothing: the index is using a "
        "tokenizer that cannot match it"
    )

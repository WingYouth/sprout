"""Heartwood contract: the memory and session-search layers.

Hermes separates two concerns; we mirror them:

- :class:`MemoryStore` — curated, hard-capped facts. ``MEMORY.md`` (session
  facts) and ``USER.md`` (user profile) live as files under a memory home
  directory. Writes go through a scanner; the cap is enforced in characters,
  not rows.
- :class:`SessionSearch` — FTS5 over the session layer (``sprout_conversation.db``), used
  by the context composer to recall past conversations across session splits.

The split keeps the two layers from sharing a database file: memory is a flat
set of markdown entries; session_search is a derived index over the
authoritative turn store.
"""

from __future__ import annotations

from typing import Protocol

from Sprout.memory.models import SearchHit, SessionFact, SessionSummary, UserFact


class MemoryStore(Protocol):
    """Curated facts: ``MEMORY.md`` (session) and ``USER.md`` (user)."""

    # -- session / working memory -------------------------------------------
    async def list_session_facts(self, session_id: str) -> list[SessionFact]: ...
    async def add_session_fact(
        self, fact: SessionFact, *, char_limit: int
    ) -> SessionFact | None:
        """Append a fact; returns the rejected fact when the cap is hit."""
        ...

    async def replace_session_fact(
        self,
        session_id: str,
        old_text: str,
        new_fact: SessionFact,
        *,
        char_limit: int,
    ) -> bool:
        """In-place edit via substring match (Hermes ``replace`` semantics)."""
        ...

    async def remove_session_fact(self, session_id: str, substring: str) -> int:
        """Drop every fact whose body contains ``substring``; returns count."""
        ...

    # -- user profile --------------------------------------------------------
    async def list_user_facts(self, user_id: str) -> list[UserFact]: ...
    async def add_user_fact(
        self, fact: UserFact, *, char_limit: int
    ) -> UserFact | None: ...
    async def replace_user_fact(
        self,
        user_id: str,
        old_text: str,
        new_fact: UserFact,
        *,
        char_limit: int,
    ) -> bool: ...
    async def remove_user_fact(self, user_id: str, substring: str) -> int: ...

    # -- rolling summary ------------------------------------------------------
    async def latest_session_summary(self, session_id: str) -> SessionSummary | None:
        """Newest rolling digest for ``session_id``; ``None`` until the first roll."""
        ...

    async def save_session_summary(self, summary: SessionSummary) -> None:
        """Append one rolling digest; ``covered_through`` only ever advances."""
        ...

    # -- snapshot / snapshot_version ----------------------------------------
    async def snapshot_version(self) -> str:
        """Stable hash of the rendered memory block; powers prefix cache."""
        ...


class SessionSearch(Protocol):
    """Cross-session full-text search over ``turns`` (sprout_conversation.db FTS5)."""

    async def index_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_seq: int,
        role: str,
        body: str,
    ) -> None: ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[SearchHit]: ...

    async def unindex_session(self, session_id: str) -> int: ...

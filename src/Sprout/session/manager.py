"""Session resolution and creation against the session store (Rootstock)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from Sprout.message.models import Message
from Sprout.session.models import Session

if TYPE_CHECKING:  # pragma: no cover - annotation only
    # Imported for typing alone: ``SessionStore`` is a Protocol used only in the
    # constructor annotation below, and this module uses PEP 563 annotations, so
    # it is never needed at runtime. A runtime import here closes a cycle —
    # ``rootstock.contract`` imports ``Sprout.session.models``, which runs
    # ``session/__init__.py``, which imports this module, which would then ask
    # ``rootstock.contract`` for a name it has not bound yet. Importing
    # ``Sprout.storage`` on its own used to fail for exactly that reason.
    from Sprout.rootstock.contract import SessionStore


class SessionManager:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def resolve(self, message: Message) -> Session:
        """Return the session referenced by the message, creating it if needed."""
        session_id = message.session_id or str(uuid4())
        session = await self._store.get_session(session_id)
        if session is None:
            session = Session(id=session_id, user_id=message.user_id)
            await self._store.save_session(session)
        return session

    async def create(self, user_id: str, *, session_id: str | None = None) -> Session:
        session = Session(id=session_id or str(uuid4()), user_id=user_id)
        await self._store.save_session(session)
        return session

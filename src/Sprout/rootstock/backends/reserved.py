"""Reserved backends: DSN slots that are scaffolded but not yet wired.

Milvus (vectors), Neo4j (graph), and Redis (hot cache) are first-class slots in
the session layer: their DSN schemes parse, the factory dispatches to them,
and they fail with a precise, actionable error instead of a surprise. Once a
client library is installed and the adapter is wired, the backend drops in
behind the same :class:`~Sprout.rootstock.contract.SessionStore` protocol.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from typing import ClassVar, NoReturn

from Sprout.rootstock.errors import RootstockUnavailableError
from Sprout.session.models import Session, Turn


class ReservedSessionStore:
    """Base class for reserved session backends.

    Subclasses declare the backend name, the required client package, and the
    planned data mapping. Construction fails fast when the package is missing;
    when the package is present but the adapter is not wired yet, every
    operation explains exactly what remains to be done.
    """

    backend_name: ClassVar[str] = "reserved"
    required_package: ClassVar[str] = ""
    plan: ClassVar[str] = ""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.package_available = (
            importlib.util.find_spec(self.required_package) is not None
            if self.required_package
            else True
        )
        if not self.package_available:
            raise RootstockUnavailableError(
                f"The {self.backend_name} session backend is reserved but the "
                f"client package '{self.required_package}' is not installed. "
                f"Install it (e.g. `uv add {self.required_package}`) and set "
                f"[storage] session = \"{dsn}\". Planned mapping: {self.plan}"
            )

    def _unwired(self) -> NoReturn:
        raise RootstockUnavailableError(
            f"The {self.backend_name} session backend is reserved and the client "
            f"package is installed, but the adapter is not wired yet. Planned "
            f"mapping: {self.plan} (DSN: {self.dsn})"
        )

    async def get_session(self, session_id: str) -> Session | None:
        self._unwired()

    async def save_session(self, session: Session) -> None:
        self._unwired()

    async def append_turn(self, turn: Turn) -> None:
        self._unwired()

    async def recent_turns(
        self, session_id: str, limit: int = 20
    ) -> Sequence[Turn]:
        self._unwired()

    async def turns_before(
        self, session_id: str, seq: int, limit: int = 100
    ) -> Sequence[Turn]:
        self._unwired()

    async def session_blob_uris(self, session_id: str) -> list[str]:
        # Consistent with every other operation on an unwired adapter: say what
        # is missing rather than answering "no blobs", which the cascade would
        # take as permission to skip cleanup.
        self._unwired()

    async def delete_session(self, session_id: str) -> int:
        self._unwired()

    async def count_sessions(self) -> int:
        self._unwired()

    async def count_turns(self) -> int:
        self._unwired()

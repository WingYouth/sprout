"""In-memory MemoryStore for tests and ephemeral runtimes."""

from __future__ import annotations

from datetime import UTC, datetime

from Sprout.memory.contract import MemoryStore
from Sprout.memory.models import SessionFact, SessionSummary, UserFact
from Sprout.memory.scanner import MemoryScanner


class MemoryMemoryStore(MemoryStore):
    """Drop-in, ephemeral backend; mirrors the file-system store in shape."""

    def __init__(self) -> None:
        self._session_facts: dict[str, dict[str, SessionFact]] = {}
        self._user_facts: dict[str, dict[str, UserFact]] = {}
        self._summaries: dict[str, list[SessionSummary]] = {}
        self._scanner = MemoryScanner()

    def _scan(self, value: str) -> bool:
        return self._scanner.scan(value).accepted

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # -- rolling summary -------------------------------------------------------
    async def latest_session_summary(self, session_id: str) -> SessionSummary | None:
        history = self._summaries.get(session_id)
        return history[-1] if history else None

    async def save_session_summary(self, summary: SessionSummary) -> None:
        self._summaries.setdefault(summary.session_id, []).append(summary)

    # -- session ----------------------------------------------------------------
    async def list_session_facts(self, session_id: str) -> list[SessionFact]:
        return list(self._session_facts.get(session_id, {}).values())

    async def add_session_fact(
        self, fact: SessionFact, *, char_limit: int
    ) -> SessionFact | None:
        if not self._scan(fact.value):
            return fact
        scope = self._session_facts.setdefault(fact.session_id, {})
        existing = sum(len(k) + len(v.value) + 4 for k, v in scope.items())
        if fact.key in scope:
            existing -= len(fact.value)
        else:
            existing += len(fact.key) + len(fact.value) + 4
        if existing > char_limit and fact.key not in scope:
            return fact
        scope[fact.key] = fact
        return None

    async def replace_session_fact(
        self,
        session_id: str,
        old_text: str,
        new_fact: SessionFact,
        *,
        char_limit: int,
    ) -> bool:
        if not self._scan(new_fact.value):
            return False
        scope = self._session_facts.get(session_id, {})
        if not any(old_text in k or old_text in v.value for k, v in scope.items()):
            return False
        existing = sum(len(k) + len(v.value) + 4 for k, v in scope.items())
        delta = len(new_fact.key) + len(new_fact.value) - sum(
            len(k) + len(v.value)
            for k, v in scope.items()
            if old_text in k or old_text in v.value
        )
        if existing + delta > char_limit:
            return False
        for k, v in list(scope.items()):
            if old_text in k or old_text in v.value:
                del scope[k]
        scope[new_fact.key] = new_fact
        return True

    async def remove_session_fact(self, session_id: str, substring: str) -> int:
        scope = self._session_facts.get(session_id, {})
        before = len(scope)
        for k, v in list(scope.items()):
            if substring in k or substring in v.value:
                del scope[k]
        return before - len(scope)

    # -- user -------------------------------------------------------------------
    async def list_user_facts(self, user_id: str) -> list[UserFact]:
        return list(self._user_facts.get(user_id, {}).values())

    async def add_user_fact(
        self, fact: UserFact, *, char_limit: int
    ) -> UserFact | None:
        if not self._scan(fact.value):
            return fact
        scope = self._user_facts.setdefault(fact.user_id, {})
        existing = sum(len(k) + len(v.value) + 4 for k, v in scope.items())
        if fact.key in scope:
            existing -= len(fact.value)
        else:
            existing += len(fact.key) + len(fact.value) + 4
        if existing > char_limit and fact.key not in scope:
            return fact
        scope[fact.key] = fact
        return None

    async def replace_user_fact(
        self,
        user_id: str,
        old_text: str,
        new_fact: UserFact,
        *,
        char_limit: int,
    ) -> bool:
        if not self._scan(new_fact.value):
            return False
        scope = self._user_facts.get(user_id, {})
        if not any(old_text in k or old_text in v.value for k, v in scope.items()):
            return False
        existing = sum(len(k) + len(v.value) + 4 for k, v in scope.items())
        delta = len(new_fact.key) + len(new_fact.value) - sum(
            len(k) + len(v.value)
            for k, v in scope.items()
            if old_text in k or old_text in v.value
        )
        if existing + delta > char_limit:
            return False
        for k, v in list(scope.items()):
            if old_text in k or old_text in v.value:
                del scope[k]
        scope[new_fact.key] = new_fact
        return True

    async def remove_user_fact(self, user_id: str, substring: str) -> int:
        scope = self._user_facts.get(user_id, {})
        before = len(scope)
        for k, v in list(scope.items()):
            if substring in k or substring in v.value:
                del scope[k]
        return before - len(scope)

    async def snapshot_version(self) -> str:
        import hashlib

        chunks: list[str] = []
        for sid, scope in sorted(self._session_facts.items()):
            for k, v in sorted(scope.items()):
                chunks.append(f"{sid}|{k}|{v.value}")
        for uid, scope in sorted(self._user_facts.items()):
            for k, v in sorted(scope.items()):
                chunks.append(f"user:{uid}|{k}|{v.value}")
        return hashlib.sha256("\n".join(chunks).encode("utf-8")).hexdigest()

    def close(self) -> None:
        return None
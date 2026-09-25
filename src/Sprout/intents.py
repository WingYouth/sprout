"""Single source of truth for runtime intent recognition and routing.

The seven intents used to be re-declared in ``runtime.py``, the intent prompt,
and the event catalog. They live here once; callers derive their tables from
:data:`INTENT_EVENTS` instead of maintaining a second copy.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from Sprout.events.catalog import (
    INTENT_APPROVAL_REQUESTED,
    INTENT_CONVERSATION_REQUESTED,
    INTENT_DELETE_REQUESTED,
    INTENT_EVOLUTION_REQUESTED,
    INTENT_MEMORY_REQUESTED,
    INTENT_STRATEGY_REQUESTED,
    INTENT_TASK_REQUESTED,
    INTENT_TOOL_REQUESTED,
    INTENT_WORKSPACE_REQUESTED,
)


class Intent(StrEnum):
    CONVERSATION = "conversation"
    TASK = "task"
    DELETE = "delete"
    WORKSPACE = "workspace"
    TOOL = "tool"
    APPROVAL = "approval"
    MEMORY = "memory"
    EVOLUTION = "evolution"
    STRATEGY = "strategy"


DEFAULT_INTENT = Intent.CONVERSATION

#: intent -> the ``intent.*.requested`` event it triggers.
INTENT_EVENTS: dict[Intent, str] = {
    Intent.CONVERSATION: INTENT_CONVERSATION_REQUESTED,
    Intent.TASK: INTENT_TASK_REQUESTED,
    Intent.DELETE: INTENT_DELETE_REQUESTED,
    Intent.WORKSPACE: INTENT_WORKSPACE_REQUESTED,
    Intent.TOOL: INTENT_TOOL_REQUESTED,
    Intent.APPROVAL: INTENT_APPROVAL_REQUESTED,
    Intent.MEMORY: INTENT_MEMORY_REQUESTED,
    Intent.EVOLUTION: INTENT_EVOLUTION_REQUESTED,
    Intent.STRATEGY: INTENT_STRATEGY_REQUESTED,
}

#: Substrings that cheaply identify a coding task without an LLM round-trip.
#: This is deliberately conservative; ambiguous text falls through to the LLM.
TASK_KEYWORDS: tuple[str, ...] = (
    "修复",
    "修改",
    "重构",
    "实现",
    "新增",
    "补充",
    "改代码",
    "写代码",
    "加个",
    "写个",
    "加一个",
    "写一个",
    "敲一个",
    "敲个",
    "帮我敲",
    "补个",
    "fix",
    "implement",
    "refactor",
    "write a",
    "add a",
    "create a",
    "modify",
)

_DELETE_VERBS = (
    "删除", "刪除", "删掉", "刪掉", "移除", "去掉", "拿掉", "清掉", "清除",
    "清理", "废弃", "廢棄", "作废", "作廢", "不要", "不需要", "不用了",
    "delete", "remove", "erase", "discard", "drop", "unlink", "get rid of",
)
_DELETE_TARGET_WORDS = (
    "文件", "檔案", "代码", "程式碼", "脚本", "模块", "模組", "file", "script",
    "module", "source",
)
_DELETE_QUESTION_MARKERS = (
    "怎么", "如何", "為什麼", "为什么", "能不能", "能否", "可以",
    "how to", "how do", "can i", "can you",
)
_DELETE_NEGATIONS = (
    "不要删除", "别删除", "別刪除", "不要删", "不要刪", "don't delete", "do not delete",
)
_FILE_PATH_HINT = re.compile(
    r"(?<![\w])(?:[\w.@+-]+(?:[/\\][\w.@+-]+)*\.[A-Za-z0-9]{1,12}|\.[\w-]+)(?!\w)"
)


_INTENT_CRITERIA: dict[str, str] = {
    Intent.CONVERSATION.value: (
        "General chat, self-description, explanation, or a question that does "
        "not request a routed operation."
    ),
    Intent.TASK.value: (
        "Create, edit, fix, refactor, implement, test, or otherwise change "
        "project files/code."
    ),
    Intent.DELETE.value: "Remove, delete, discard, clean up, or make a file/source/module go away.",
    Intent.WORKSPACE.value: (
        "Inspect, scan, analyze, or answer questions about the "
        "project/workspace without changing files."
    ),
    Intent.TOOL.value: (
        "Run a command, build, install, download, invoke a CLI, or use an "
        "external tool."
    ),
    Intent.APPROVAL.value: (
        "Approve, reject, resume, decide, or ask about a pending "
        "permission/approval."
    ),
    Intent.MEMORY.value: "Remember, forget, recall, store, or manage user/session memory.",
    Intent.EVOLUTION.value: (
        "Create, improve, install, search, or consolidate skills or "
        "self-improvement knowledge."
    ),
    Intent.STRATEGY.value: (
        "Plan, decompose, estimate impact, or produce an execution strategy "
        "without immediately changing files."
    ),
}


class LayaIntentError(RuntimeError):
    """Raised when the laya intent router cannot be used."""


class LayaIntentRecognizer:
    """Intent recognition through laya's System 1 router."""

    _router_instance: Any | None = None

    def __init__(self, router_factory: Callable[[], Any] | None = None) -> None:
        self._router_factory = router_factory

    def classify(self, state: Mapping[str, Any]) -> dict[str, Any]:
        router = self._get_router()
        result = router.predict(
            dict(state),
            self.questions(),
            task="intent",
            max_len=512,
            head_max_len=256,
        )
        return self._decode(result)

    @classmethod
    def questions(cls) -> dict[str, dict[str, Any]]:
        return {
            "intent": {
                "type": "choice",
                "instructions": (
                    "Choose the single best SEAM Sprout runtime intent for the "
                    "latest user message. Use recent conversation and metadata only "
                    "as context; classify the operation the user is asking for now."
                ),
                "criteria": dict(_INTENT_CRITERIA),
            }
        }

    def _get_router(self) -> Any:
        if self._router_factory is not None:
            return self._router_factory()
        if self.__class__._router_instance is None:
            try:
                from laya import Router
            except ModuleNotFoundError as exc:
                raise LayaIntentError(
                    "Intent recognition requires the 'laya' package. Install it with "
                    "`uv pip install laya` or sync project dependencies."
                ) from exc
            self.__class__._router_instance = Router(preload=False)
        return self.__class__._router_instance

    @staticmethod
    def _decode(result: Mapping[str, Any]) -> dict[str, Any]:
        answers = result.get("answers") if isinstance(result, Mapping) else None
        answer = answers.get("intent") if isinstance(answers, Mapping) else None
        if not isinstance(answer, Mapping):
            return {
                "intent": DEFAULT_INTENT.value,
                "trigger_event": intent_event(DEFAULT_INTENT),
                "confidence": 0.0,
                "reason": "laya_missing_intent_answer",
            }
        intent = normalize_intent(str(answer.get("choice") or ""))
        confidence = _float_confidence(
            answer.get("answer_confidence", answer.get("confidence", 0.0))
        )
        probabilities = answer.get("probabilities")
        return {
            "intent": intent.value,
            "trigger_event": intent_event(intent),
            "confidence": confidence,
            "reason": "laya_router",
            **(
                {"intent_probabilities": dict(probabilities)}
                if isinstance(probabilities, Mapping)
                else {}
            ),
        }


def laya_intent_state(
    *,
    message: str,
    channel: str = "",
    user_id: str = "",
    message_metadata: Mapping[str, Any] | None = None,
    context_metadata: Mapping[str, Any] | None = None,
    memory: Mapping[str, Any] | None = None,
    recent_conversation: Sequence[Mapping[str, Any]] = (),
    similar_context: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the state payload passed to laya for intent recognition."""
    return {
        "message": message,
        "channel": channel,
        "user_id": user_id,
        "message_metadata": dict(message_metadata or {}),
        "context_metadata": dict(context_metadata or {}),
        "memory": dict(memory or {}),
        "recent_conversation": [dict(item) for item in recent_conversation],
        "similar_context_from_vector_db": [dict(item) for item in similar_context],
    }


def _float_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_intent(value: str | None) -> Intent:
    """Coerce a raw intent name to a known :class:`Intent`, defaulting safely."""
    if not value:
        return DEFAULT_INTENT
    try:
        return Intent(value)
    except ValueError:
        return DEFAULT_INTENT


def intent_event(intent: Intent | str) -> str:
    return INTENT_EVENTS[normalize_intent(str(intent))]


def detect_task_hint(text: str) -> bool:
    """True when ``text`` looks like an explicit coding task (slash or keyword)."""
    stripped = text.strip()
    if stripped == "/task" or stripped.startswith("/task "):
        return True
    lowered = stripped.casefold()
    # A question about ability or permission ("can you write code?", "can you
    # help me?") is not an instruction to change files. It must not trip the
    # workspace-consent gate: that gate interrupts a conversation and asks for a
    # directory, which is exactly wrong for a yes/no question.
    if lowered.endswith(("吗", "么", "?", "？")):
        if any(
            phrase in lowered
            for phrase in ("能帮我", "可以帮我", "能不能", "可以吗", "能吗")
        ):
            return False
    return detect_delete_hint(stripped) or any(
        keyword in lowered for keyword in TASK_KEYWORDS
    )


def detect_delete_hint(text: str) -> bool:
    """Recognize an explicit file deletion request without an LLM call."""
    lowered = text.casefold().strip()
    if not any(verb in lowered for verb in _DELETE_VERBS):
        return False
    if any(negation in lowered for negation in _DELETE_NEGATIONS):
        return False
    if lowered.endswith(("?", "？", "吗", "嗎")) and any(
        marker in lowered for marker in _DELETE_QUESTION_MARKERS
    ):
        return False
    return bool(_FILE_PATH_HINT.search(lowered)) or any(
        target in lowered for target in _DELETE_TARGET_WORDS
    )


__all__ = [
    "DEFAULT_INTENT",
    "INTENT_EVENTS",
    "TASK_KEYWORDS",
    "Intent",
    "LayaIntentError",
    "LayaIntentRecognizer",
    "detect_task_hint",
    "detect_delete_hint",
    "intent_event",
    "laya_intent_state",
    "normalize_intent",
]

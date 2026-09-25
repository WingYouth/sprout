"""Single source of truth for runtime intent recognition and routing.

The seven intents used to be re-declared in ``runtime.py``, the intent prompt,
and the event catalog. They live here once; callers derive their tables from
:data:`INTENT_EVENTS` instead of maintaining a second copy.
"""

from __future__ import annotations

from enum import StrEnum

from Sprout.events.catalog import (
    INTENT_APPROVAL_REQUESTED,
    INTENT_CONVERSATION_REQUESTED,
    INTENT_EVOLUTION_REQUESTED,
    INTENT_MEMORY_REQUESTED,
    INTENT_TASK_REQUESTED,
    INTENT_TOOL_REQUESTED,
    INTENT_WORKSPACE_REQUESTED,
)


class Intent(StrEnum):
    CONVERSATION = "conversation"
    TASK = "task"
    WORKSPACE = "workspace"
    TOOL = "tool"
    APPROVAL = "approval"
    MEMORY = "memory"
    EVOLUTION = "evolution"


DEFAULT_INTENT = Intent.CONVERSATION

#: intent -> the ``intent.*.requested`` event it triggers.
INTENT_EVENTS: dict[Intent, str] = {
    Intent.CONVERSATION: INTENT_CONVERSATION_REQUESTED,
    Intent.TASK: INTENT_TASK_REQUESTED,
    Intent.WORKSPACE: INTENT_WORKSPACE_REQUESTED,
    Intent.TOOL: INTENT_TOOL_REQUESTED,
    Intent.APPROVAL: INTENT_APPROVAL_REQUESTED,
    Intent.MEMORY: INTENT_MEMORY_REQUESTED,
    Intent.EVOLUTION: INTENT_EVOLUTION_REQUESTED,
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
    "补个",
    "fix",
    "implement",
    "refactor",
    "write a",
    "add a",
    "create a",
    "modify",
)


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
    return any(keyword in lowered for keyword in TASK_KEYWORDS)


__all__ = [
    "DEFAULT_INTENT",
    "INTENT_EVENTS",
    "TASK_KEYWORDS",
    "Intent",
    "detect_task_hint",
    "intent_event",
    "normalize_intent",
]

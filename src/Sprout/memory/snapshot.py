"""Frozen memory snapshot: a per-session hash of the rendered memory block.

The rendered block is fed to the model as part of the system prompt. If we
rebuild it every turn we invalidate the LLM prefix cache on every keystroke;
if we freeze it for a session and pin a ``snapshot_hash``, the prefix stays
warm until the user edits memory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.memory.models import ContextMemory

#: Sentinel for "this object has no ``summary`` attribute", i.e. it is not a
#: :class:`ContextMemory` but a plain sequence of turns.
_MISSING = object()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A hash of the rendered memory block, plus the rendered text."""

    hash: str
    text: str


def memory_block_for(memory: object) -> str:
    """The rendered memory block to inject, or "" when there is nothing to say.

    The block carries what the *working window* cannot: the summary, the curated
    facts, and the recalled snippets. Only turns reach the model through
    ``history_messages`` (it iterates the memory object), so without this the
    four non-turn parts of a :class:`ContextMemory` were assembled, persisted
    for audit, and never actually sent — the model answered with no recall of
    anything outside the current window.

    Returns "" for a plain turn sequence (``history_messages`` accepts one), so
    callers that pass no ``ContextMemory`` are unaffected.
    """
    render = getattr(memory, "summary", _MISSING)
    if render is _MISSING:  # not a ContextMemory
        return ""
    body = render_snapshot(memory).text  # type: ignore[arg-type]
    # A block holding only the "# Memory" heading says nothing; injecting it
    # would add a system message to every turn for no benefit.
    return body if body.strip() and body.strip() != "# Memory" else ""


def render_snapshot(memory: ContextMemory, *, header: str = "") -> Snapshot:
    """Render the memory block into one system-prompt-ready string and hash it."""
    lines: list[str] = [header] if header else []
    lines.append("# Memory")
    if memory.summary is not None:
        lines.append("## Summary")
        lines.append(memory.summary.content)
        lines.append("")
    if memory.facts:
        lines.append("## Facts")
        for fact in memory.facts:
            owner = getattr(fact, "user_id", None) or "session"
            lines.append(f"- [{owner}] {fact.key}: {fact.value}")
        lines.append("")
    if memory.recalled:
        lines.append("## Recalled snippets")
        for hit in memory.recalled:
            lines.append(f"- (seq {hit.turn_seq}) {hit.snippet}")
        lines.append("")
    text = "\n".join(lines).rstrip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Snapshot(hash=digest, text=text)


def diff_hashes(prev: Iterable[str], current: str) -> bool:
    """True when the current snapshot is *different* from any previous hash."""
    target = current
    for entry in prev:
        if entry == target:
            return False
    return True


__all__ = ["Snapshot", "render_snapshot", "diff_hashes"]
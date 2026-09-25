"""Minimal unified-diff parser and applier for the sandbox patch tool.

The model emits standard unified diff (``git diff`` / ``diff -u``) shaped text;
this module turns it into ``(path, hunks)`` pairs and applies each hunk with
context verification so a wrong guess fails loudly instead of corrupting a file.

Locating a hunk is deliberately more forgiving than byte equality. A model
writing a patch from memory reproduces *meaning* reliably and whitespace
unreliably: it drops a trailing space it cannot see, or writes an ASCII hyphen
where the file holds a typographic dash (``–``). Requiring an exact match made
every such patch fail the whole tool call, so the search escalates through four
passes — exact, then trailing-whitespace-insensitive, then fully trimmed, then
Unicode-punctuation-normalised — and reports which pass matched.

Escalating is not the same as guessing. Every hunk carries a line number, so a
relaxed match is only accepted at the position the file itself points to, and
the punctuation pass — the only one that can make a *semantically* different
line look equal — additionally refuses to choose between equally good
candidates. See :func:`_locate`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    """Raised when a patch cannot be parsed or applied."""


@dataclass(frozen=True, slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    #: ``(op, text)`` where ``op`` is one of ``context`` / ``delete`` / ``add``.
    ops: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class FilePatch:
    path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_delete: bool = False
    rename_from: str = ""


#: Typographic punctuation folded to its ASCII equivalent in the last matching
#: pass. Restricted on purpose: a patch authored in ASCII should still apply to
#: a file whose prose uses en dashes and curly quotes, but no substitution here
#: may collapse characters a reader would call *different words*.
_FOLD = str.maketrans(
    {
        **{chr(code): "-" for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)},
        **{chr(code): "'" for code in (0x2018, 0x2019, 0x201A, 0x201B)},
        **{chr(code): '"' for code in (0x201C, 0x201D, 0x201E, 0x201F)},
        **{
            chr(code): " "
            for code in (
                0x00A0, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008,
                0x2009, 0x200A, 0x202F, 0x205F, 0x3000,
            )
        },
    }
)

#: Pass names, mildest first. Reported in the error text for a refusal so the
#: caller can tell "your context does not match" from "your context is too
#: ambiguous to trust".
_EXACT = "exact"
_RSTRIP = "trailing whitespace"
_TRIM = "whitespace"
_PUNCT = "typographic punctuation"

#: The passes below ``_PUNCT`` may only relocate *within* the whitespace the
#: caller can already see; ``_PUNCT`` is the only one that can equate lines a
#: reader might call different, so it is guarded separately in :func:`_locate`.
_FUZZY_PASSES = (_RSTRIP, _TRIM)


def parse_patch(patch: str) -> list[FilePatch]:
    """Parse a unified diff into one :class:`FilePatch` per touched file."""
    files: list[FilePatch] = []
    current: FilePatch | None = None
    current_hunk: tuple[int, int, int, int, list[tuple[str, str]]] | None = None
    pending_old_path: str | None = None
    pending_rename_from: str | None = None

    def _flush_hunk() -> None:
        nonlocal current_hunk
        if current is None or current_hunk is None:
            return
        old_start, old_count, new_start, new_count, ops = current_hunk
        current.hunks.append(
            Hunk(old_start, old_count, new_start, new_count, tuple(ops))
        )
        current_hunk = None

    for raw in patch.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("--- "):
            _flush_hunk()
            if current is not None:
                files.append(current)
                current = None
                current_hunk = None
            pending_old_path = _parse_target_path(line)
            continue
        if line.startswith("+++ "):
            _flush_hunk()
            if current is not None:
                files.append(current)
                current = None
            target = _parse_target_path(line)
            if _is_dev_null(line):
                current = FilePatch(
                    path=pending_old_path or target,
                    is_delete=True,
                )
            else:
                current = FilePatch(path=target)
            pending_old_path = None
            continue
        if line.startswith("rename from "):
            pending_rename_from = _parse_rename_path(line, "rename from ")
            continue
        if line.startswith("rename to "):
            rename_to = _parse_rename_path(line, "rename to ")
            _flush_hunk()
            if current is not None:
                files.append(current)
                current = None
            if pending_rename_from and rename_to:
                files.append(
                    FilePatch(path=rename_to, rename_from=pending_rename_from)
                )
            pending_rename_from = None
            continue
        if current is None:
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match:
            _flush_hunk()
            old_start = int(match.group(1))
            old_count = int(match.group(2) or 1)
            new_start = int(match.group(3))
            new_count = int(match.group(4) or 1)
            current_hunk = (old_start, old_count, new_start, new_count, [])
            continue
        if current_hunk is None:
            continue
        if line.startswith(" "):
            current_hunk[4].append(("context", line[1:]))
        elif line.startswith("-"):
            current_hunk[4].append(("delete", line[1:]))
        elif line.startswith("+"):
            current_hunk[4].append(("add", line[1:]))
        # ``\ No newline at end of file`` and blank lines are skipped.

    _flush_hunk()
    if current is not None:
        files.append(current)
    if not files or any(
        not file.hunks and not file.is_delete and not file.rename_from
        for file in files
    ):
        raise PatchError("patch contains no files or hunks")
    return files


def _candidates(last_start: int, hint: int) -> list[int]:
    """Every start position a pattern of this length could occupy.

    Ordered nearest-to-``hint`` first so a fuzzy pass settles on the occurrence
    the hunk's own line number points at rather than the first one in the file —
    the file tells us where it meant, so there is no reason to ignore it.
    Ties break on the lower index, keeping the result independent of sort
    stability.
    """
    return sorted(range(last_start + 1), key=lambda index: (abs(index - hint), index))


def _matches_exact(lines: list[str], pattern: list[str], at: int) -> bool:
    return lines[at : at + len(pattern)] == pattern


def _matches_rstrip(lines: list[str], pattern: list[str], at: int) -> bool:
    return all(
        lines[at + offset].rstrip() == text.rstrip()
        for offset, text in enumerate(pattern)
    )


def _matches_trim(lines: list[str], pattern: list[str], at: int) -> bool:
    return all(
        lines[at + offset].strip() == text.strip()
        for offset, text in enumerate(pattern)
    )


def _matches_fold(lines: list[str], pattern: list[str], at: int) -> bool:
    return all(
        lines[at + offset].strip().translate(_FOLD) == text.strip().translate(_FOLD)
        for offset, text in enumerate(pattern)
    )


_MATCHERS = {
    _EXACT: _matches_exact,
    _RSTRIP: _matches_rstrip,
    _TRIM: _matches_trim,
}


def _locate(
    lines: list[str], pattern: list[str], hint: int
) -> tuple[int, str] | None:
    """Where ``pattern`` sits in ``lines``, and how hard it was to find.

    ``hint`` is the line number the hunk claims, already offset-corrected. It is
    used three ways: as the preferred position within an equally-good pass, as
    the tie-break, and — for the punctuation pass alone — as the corroborating
    evidence required to act.

    Returns ``(index, pass_name)``, or ``None`` when no pass matches. A refusal
    is always preferable to a wrong application: the caller reports it.
    """
    if not pattern:
        # Nothing to verify (a pure insertion). The line number is all there is,
        # clamped so an end-of-file append cannot address past the last line.
        return min(max(hint, 0), len(lines)), _EXACT

    if len(pattern) > len(lines):
        # Cannot fit anywhere. Returning None here is also what keeps the slice
        # arithmetic below in range.
        return None

    last_start = len(lines) - len(pattern)
    candidates = _candidates(last_start, hint)

    for name in (_EXACT, *_FUZZY_PASSES):
        matcher = _MATCHERS[name]
        for index in candidates:
            if matcher(lines, pattern, index):
                return index, name

    # Last resort: punctuation folding. Unlike the whitespace passes this
    # equates lines that differ in *content*, so it acts only when the file
    # corroborates the choice — either the hunk's own line number folds to a
    # match, or exactly one position in the whole file does. Two equally good
    # candidates and no line number agreeing means the patch is ambiguous, and
    # picking one would be writing a guess into the user's file.
    folded = [index for index in candidates if _matches_fold(lines, pattern, index)]
    if not folded:
        return None
    if hint in folded:
        return hint, _PUNCT
    if len(folded) == 1:
        return folded[0], _PUNCT
    return None


def apply_hunks(lines: list[str], hunk: Hunk, *, offset: int = 0) -> list[str]:
    """Apply one hunk to a line list, locating its context before rewriting.

    ``offset`` is how far the preceding hunks have already shifted the file; it
    corrects the hint, and a hunk that no longer sits exactly there is found by
    :func:`_locate` rather than being rejected.
    """
    if hunk.old_start < 0:
        raise PatchError("invalid hunk start")

    hint = max(hunk.old_start - 1 + offset, 0)
    pattern = [text for op, text in hunk.ops if op != "add"]
    located = _locate(lines, pattern, hint)
    if located is None:
        raise PatchError(
            f"cannot locate hunk at line {hunk.old_start}: "
            f"no line in the file matches this context"
        )
    cursor, _how = located

    result = lines[:cursor]
    for op, text in hunk.ops:
        if op == "context":
            # The file's own line, not the patch's copy of it. A context line is
            # unchanged by definition, so copying the patch's text would let a
            # whitespace-damaged patch silently rewrite lines it never meant to
            # touch.
            result.append(lines[cursor])
            cursor += 1
        elif op == "delete":
            cursor += 1
        elif op == "add":
            result.append(text)
    result.extend(lines[cursor:])
    return result


def apply_patch_to_text(text: str, file_patch: FilePatch) -> str:
    """Apply every hunk of a file patch to ``text`` and return the new text."""
    lines = text.split("\n")
    had_trailing_newline = text.endswith("\n")
    if had_trailing_newline and lines and lines[-1] == "":
        lines = lines[:-1]

    offset = 0
    for hunk in sorted(file_patch.hunks, key=lambda item: item.old_start):
        lines = apply_hunks(lines, hunk, offset=offset)
        # Counted from the ops rather than taken from the header: a model that
        # miscounts ``@@ -a,b +c,d @@`` would otherwise shift every later hunk
        # by the error. The ops are what actually got applied.
        offset += sum(1 for op, _ in hunk.ops if op == "add") - sum(
            1 for op, _ in hunk.ops if op == "delete"
        )

    joined = "\n".join(lines)
    if had_trailing_newline:
        joined += "\n"
    return joined


def _parse_target_path(line: str) -> str:
    """Extract a sandbox-relative path from a ``+++ b/...`` header."""
    raw = line[4:].strip()
    # Strip the conventional ``a/`` / ``b/`` prefixes and any tab-timestamp tail.
    raw = raw.split("\t", 1)[0].strip()
    for prefix in ("b/", "a/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw


def _is_dev_null(line: str) -> bool:
    """Whether a ``+++`` header points at ``/dev/null`` (a deletion)."""
    raw = line[4:].strip().split("\t", 1)[0].strip()
    return raw in {"/dev/null", "dev/null"}


def _parse_rename_path(line: str, prefix: str) -> str:
    raw = line[len(prefix) :].strip()
    for candidate in ("b/", "a/"):
        if raw.startswith(candidate):
            raw = raw[len(candidate) :]
            break
    return raw


__all__ = [
    "FilePatch",
    "Hunk",
    "PatchError",
    "apply_hunks",
    "apply_patch_to_text",
    "parse_patch",
]

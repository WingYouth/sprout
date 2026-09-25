"""Tests for the unified-diff parser and applier used by sandbox_apply_patch."""

from __future__ import annotations

import pytest

from Sprout.execution.patch import (
    PatchError,
    apply_patch_to_text,
    parse_patch,
)


def test_parse_patch_splits_multiple_files_and_hunks() -> None:
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "+b\n"
        " c\n"
        "--- a/b.py\n"
        "+++ b/b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )

    files = parse_patch(patch)

    assert [file.path for file in files] == ["a.py", "b.py"]
    assert len(files[0].hunks) == 1
    assert files[0].hunks[0].old_count == 2
    assert files[0].hunks[0].new_count == 3


def test_apply_patch_replaces_one_hunk() -> None:
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 1\n"
        "+    return 2\n"
    )

    result = apply_patch_to_text("def foo():\n    return 1\n", parse_patch(patch)[0])

    assert result == "def foo():\n    return 2\n"


def test_apply_patch_handles_offsets_between_hunks() -> None:
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "+b\n"
        " c\n"
        "@@ -4,1 +5,1 @@\n"
        " e\n"
        "-f\n"
        "+g\n"
    )

    result = apply_patch_to_text(
        "a\nc\nd\ne\nf\n",
        parse_patch(patch)[0],
    )

    assert result == "a\nb\nc\nd\ne\ng\n"


def test_apply_patch_creates_new_file() -> None:
    patch = (
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+hello\n"
        "+world\n"
    )

    result = apply_patch_to_text("", parse_patch(patch)[0])

    assert result == "hello\nworld\n"


def test_apply_patch_rejects_context_mismatch() -> None:
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-wrong\n"
        "+right\n"
    )

    with pytest.raises(PatchError, match="cannot locate hunk"):
        apply_patch_to_text("actual\n", parse_patch(patch)[0])


def test_parse_patch_requires_at_least_one_hunk() -> None:
    with pytest.raises(PatchError, match="no files or hunks"):
        parse_patch("--- a/a.py\n+++ b/a.py\n")


def test_parse_patch_recognizes_a_file_deletion() -> None:
    files = parse_patch(
        "--- a/a.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-print('gone')\n"
    )

    assert len(files) == 1
    assert files[0].path == "a.py"
    assert files[0].is_delete is True


def test_parse_patch_recognizes_a_pure_rename() -> None:
    files = parse_patch(
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )

    assert len(files) == 1
    assert files[0].path == "new.py"
    assert files[0].rename_from == "old.py"


# -- locating a hunk when the patch's context is imperfect -------------------


def _replace(old: str, new: str) -> str:
    """A one-line replacement patch, the shape that exercises the matcher."""
    return (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def test_hunk_applies_when_the_file_has_trailing_whitespace() -> None:
    """A model cannot see trailing spaces, so it does not reproduce them.

    Exact matching made the whole tool call fail over whitespace the patch's
    author had no way to observe.
    """
    result = apply_patch_to_text(
        "value = 1   \n", parse_patch(_replace("value = 1", "value = 2"))[0]
    )

    assert result == "value = 2\n"


def test_hunk_applies_when_indentation_is_reformatted() -> None:
    """Fully-trimmed comparison, for context the model re-indented.

    The replacement is the *patch's* text, indentation included: this hunk is
    changing the line, so the model's version of it is the intended one. Only
    context lines keep the file's own whitespace.
    """
    result = apply_patch_to_text(
        "    return 1\n", parse_patch(_replace("  return 1", "  return 2"))[0]
    )

    assert result == "  return 2\n"


def test_hunk_applies_across_typographic_punctuation() -> None:
    """ASCII patch, typographic file — the case that motivated the fold pass.

    The file's comment holds an EN DASH; the patch writes a plain hyphen. Under
    exact matching this was a hard failure, and the deleted line is the one
    carrying the dash, so nothing weaker than folding can bridge it.
    """
    result = apply_patch_to_text(
        "import x  # local import – avoids dep\n",
        parse_patch(_replace("import x  # local import - avoids dep", "import x  # ok"))[0],
    )

    assert result == "import x  # ok\n"


def test_a_context_line_keeps_the_files_own_whitespace() -> None:
    """Fuzzy matching locates a hunk; it must not rewrite what it did not touch.

    The context line differs from the patch's copy by a tab. Writing the
    patch's version back would be an unrequested edit — the very corruption the
    strict comparison existed to prevent.
    """
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-  return 1\n"
        "+  return 2\n"
    )

    result = apply_patch_to_text(
        "def foo():\t\n  return 1\n", parse_patch(patch)[0]
    )

    assert result == "def foo():\t\n  return 2\n"


def test_a_misnumbered_hunk_is_found_rather_than_rejected() -> None:
    """The line number is a hint, not a precondition.

    A model writing ``@@ -1`` for a hunk that is really at line 4 still means
    the hunk; the context is what identifies it.
    """
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-target\n"
        "+replaced\n"
    )

    result = apply_patch_to_text(
        "one\ntwo\nthree\ntarget\nfive\n", parse_patch(patch)[0]
    )

    assert result == "one\ntwo\nthree\nreplaced\nfive\n"


def test_an_ambiguous_folded_match_is_refused() -> None:
    """Folding must not pick between two equally good candidates.

    Both lines fold to the same text — one holds an EN DASH, the other an EM
    DASH — and the hunk's line number agrees with neither, so there is no
    evidence for either. Applying one would be writing a guess into the file,
    which is the one thing the fuzzy passes must never do.
    """
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -9,1 +9,1 @@\n"
        "-# a - b\n"
        "+# merged\n"
    )

    with pytest.raises(PatchError, match="cannot locate hunk"):
        apply_patch_to_text("# a – b\n# a — b\n", parse_patch(patch)[0])


def test_a_folded_match_is_taken_when_the_line_number_corroborates_it() -> None:
    """Same ambiguity, but the hunk's own line number breaks the tie."""
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -2,1 +2,1 @@\n"
        "-# a - b\n"
        "+# merged\n"
    )

    result = apply_patch_to_text(
        "# keep\n# a – b\n", parse_patch(patch)[0]
    )

    assert result == "# keep\n# merged\n"


def test_whitespace_matching_succeeds_where_folding_must_refuse() -> None:
    """Escalation is ordered for a reason, and this is it.

    The file holds an EN DASH on one line and an ASCII hyphen with a trailing
    space on the next, so *nothing* matches exactly. Ignoring trailing
    whitespace, the second line matches uniquely and the hunk lands; the
    punctuation pass, which equates both lines, sees an ambiguity and would have
    to refuse. Running fold first, or alone, rejects a patch that is not
    actually ambiguous.
    """
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -9,1 +9,1 @@\n"
        "-# x - y\n"
        "+# merged\n"
    )

    result = apply_patch_to_text("# x – y\n# x - y \n", parse_patch(patch)[0])

    assert result == "# x – y\n# merged\n"


def test_the_applied_offset_comes_from_the_ops_not_the_header() -> None:
    """A miscounted ``@@ -a,b +c,d @@`` must not shift every later hunk.

    Hunks are applied in file order, so an offset taken from a wrong header
    count compounds; the ops are what actually get applied.
    """
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,1 +1,9 @@\n"
        " first\n"
        "+inserted\n"
        "@@ -3,1 +3,1 @@\n"
        " third\n"
        "-old\n"
        "+new\n"
    )

    result = apply_patch_to_text(
        "first\nsecond\nthird\nold\n", parse_patch(patch)[0]
    )

    assert result == "first\ninserted\nsecond\nthird\nnew\n"

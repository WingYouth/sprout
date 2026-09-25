from __future__ import annotations

from io import StringIO

from rich.console import Console

from Sprout.cli.diff import render_diff


def test_render_diff_shows_file_totals_and_old_new_line_numbers() -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, width=100)
    diff = """diff --git a/src/example.py b/src/example.py
index 1234567..abcdef0 100644
--- a/src/example.py
+++ b/src/example.py
@@ -4,3 +4,4 @@
 before()
-old_call()
+new_call()
+extra_call()
 after()
"""

    render_diff("src/example.py", diff, console=console)

    output = stream.getvalue()
    assert "Diff src/example.py  M  +2  -1" in output
    assert "    5       │ -old_call()" in output
    assert "             5 │ +new_call()" in output
    assert "             6 │ +extra_call()" in output
    assert "     6     7 │ after()" in output


def test_render_diff_marks_deleted_files_and_counts_removed_lines() -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, width=100)
    diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-first()
-second()
"""

    render_diff("old.py", diff, console=console)

    output = stream.getvalue()
    assert "Diff old.py  D  +0  -2" in output
    assert "    1       │ -first()" in output
    assert "    2       │ -second()" in output

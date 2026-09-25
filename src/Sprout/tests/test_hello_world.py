"""Verification for the root-level ``hello_world.py`` reference example.

``hello_world.py`` lives at the repository root rather than inside the installed
``Sprout`` package, so the root has to be on ``sys.path`` before it can be
imported. ``[tool.pytest.ini_options] pythonpath = ["."]`` already does this, and
the explicit insert below keeps the test correct when it is run from a rootdir
that does not carry that setting.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: ``src/Sprout/tests/test_hello_world.py`` -> repository root.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import hello_world as module  # noqa: E402
from hello_world import GREETING, hello  # noqa: E402


def test_builtin_self_check_passes() -> None:
    # The module ships its own checks; running them here keeps the two in step.
    module._self_check()


def test_default_greeting_when_no_name_is_given() -> None:
    assert hello() == "Hello, World!"
    assert hello(None) == "Hello, World!"
    assert GREETING == "Hello, World!"


def test_blank_names_fall_back_to_the_default_greeting() -> None:
    assert hello("") == "Hello, World!"
    assert hello("   ") == "Hello, World!"
    assert hello("\t\n") == "Hello, World!"


def test_name_is_interpolated() -> None:
    assert hello("Sprout") == "Hello, Sprout!"


def test_surrounding_whitespace_is_stripped() -> None:
    assert hello("  Sprout  ") == "Hello, Sprout!"


def test_returns_a_string_instead_of_printing(capsys) -> None:
    result = hello()
    assert isinstance(result, str)
    assert capsys.readouterr().out == ""


def test_main_prints_the_greeting(capsys) -> None:
    module.main()
    assert capsys.readouterr().out == "Hello, World!\n"

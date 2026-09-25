"""Verification for the root-level ``bubble_sort.py`` reference implementation.

``bubble_sort.py`` lives at the repository root rather than inside the installed
``Sprout`` package, so the root has to be on ``sys.path`` before it can be
imported. ``[tool.pytest.ini_options] pythonpath = ["."]`` already does this, and
the explicit insert below keeps the test correct when it is run from a rootdir
that does not carry that setting.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

#: ``src/Sprout/tests/test_bubble_sort.py`` -> repository root.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bubble_sort as module  # noqa: E402
from bubble_sort import bubble_sort  # noqa: E402


def test_builtin_self_check_passes() -> None:
    # The module ships its own checks; running them here keeps the two in step.
    module._self_check()


def test_empty_and_single_element_inputs() -> None:
    assert bubble_sort([]) == []
    assert bubble_sort([42]) == [42]


def test_sorts_unsorted_input() -> None:
    assert bubble_sort([5, 1, 4, 2, 8]) == [1, 2, 4, 5, 8]


def test_already_sorted_and_reverse_sorted_input() -> None:
    assert bubble_sort([1, 2, 3]) == [1, 2, 3]
    assert bubble_sort([3, 2, 1]) == [1, 2, 3]


def test_duplicates_are_preserved() -> None:
    assert bubble_sort([2, 2, 1]) == [1, 2, 2]


def test_floats_and_strings() -> None:
    assert bubble_sort([1.5, -0.5, 3.0]) == [-0.5, 1.5, 3.0]
    assert bubble_sort(["b", "a", "c"]) == ["a", "b", "c"]


def test_reverse_sorts_descending() -> None:
    assert bubble_sort([5, 1, 4], reverse=True) == [5, 4, 1]


def test_key_sorts_by_mapped_value_and_returns_originals() -> None:
    words = ["banana", "kiwi", "apple"]
    assert bubble_sort(words, key=len) == ["kiwi", "apple", "banana"]


def test_key_keeps_stability_for_equal_keys() -> None:
    stable = [(1, "first"), (0, "zero"), (1, "second"), (0, "zed")]
    assert bubble_sort(stable, key=lambda pair: pair[0]) == [
        (0, "zero"),
        (0, "zed"),
        (1, "first"),
        (1, "second"),
    ]


def test_sorts_in_place_and_returns_the_same_object() -> None:
    original = [3, 1, 2]
    result = bubble_sort(original)
    assert result is original
    assert original == [1, 2, 3]


def test_matches_the_standard_library_on_a_fixed_sample() -> None:
    random.seed(20240924)
    sample = [random.randint(-100, 100) for _ in range(200)]
    assert bubble_sort(list(sample)) == sorted(sample)
    assert bubble_sort(list(sample), reverse=True) == sorted(sample, reverse=True)

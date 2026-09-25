"""Root-level reference example: an in-place bubble sort with a stable contract.

Like the other root-level examples, this file is deliberately *outside* ``src/Sprout``. It is
the next smallest complete target the runtime can be pointed at end to end: a
pure-ish function that mutates the sequence it is given, a ``main()`` entry
point, and a self-check that needs no test runner.

    python bubble_sort.py     # prints: [1, 2, 4, 5, 8]

``bubble_sort`` sorts its argument **in place** and returns that same object,
which is the one behavioural surprise worth pinning down: callers that want a
fresh list must pass a copy. Key mapping is only used for comparison, and equal
keys never swap, so the sort is stable.

The contract is pinned by ``src/Sprout/tests/test_bubble_sort.py``.
"""

from __future__ import annotations

from collections.abc import Callable, MutableSequence

__all__ = ["bubble_sort", "main"]


def bubble_sort[T](
    items: MutableSequence[T],
    *,
    key: Callable[[T], object] | None = None,
    reverse: bool = False,
) -> MutableSequence[T]:
    """Sort ``items`` in place with bubble sort and return the same object.

    ``key`` (like :func:`sorted`) computes the value compared, while the original
    elements are what moves and what is returned. ``reverse=True`` gives
    descending order.

    Comparison is strict (``>`` ascending, ``<`` descending), so elements with
    equal keys keep their relative order — the sort is stable. A pass with no
    swap means the sequence is already ordered and the loop stops early.
    """
    size = len(items)
    if size < 2:
        return items

    project: Callable[[T], object] = key if key is not None else lambda value: value

    for end in range(size - 1, 0, -1):
        swapped = False
        for index in range(end):
            left = project(items[index])
            right = project(items[index + 1])
            out_of_order = left < right if reverse else left > right
            if out_of_order:
                items[index], items[index + 1] = items[index + 1], items[index]
                swapped = True
        if not swapped:
            break

    return items


def main() -> None:
    """Print the fixed sample sorted ascending."""
    print(bubble_sort([5, 1, 4, 2, 8]))


def _self_check() -> None:
    """Assert the module's own contract; used by the test suite and ad hoc runs."""
    # Empty and single-element inputs are returned untouched.
    assert bubble_sort([]) == []
    assert bubble_sort([42]) == [42]

    # Plain ascending order, already-sorted and reverse-sorted inputs.
    assert bubble_sort([5, 1, 4, 2, 8]) == [1, 2, 4, 5, 8]
    assert bubble_sort([1, 2, 3]) == [1, 2, 3]
    assert bubble_sort([3, 2, 1]) == [1, 2, 3]
    assert bubble_sort([2, 2, 1]) == [1, 2, 2]

    # Mixed comparable types.
    assert bubble_sort([1.5, -0.5, 3.0]) == [-0.5, 1.5, 3.0]
    assert bubble_sort(["b", "a", "c"]) == ["a", "b", "c"]

    # Descending order.
    assert bubble_sort([5, 1, 4], reverse=True) == [5, 4, 1]

    # ``key`` compares the mapped value but returns the original elements.
    assert bubble_sort(["banana", "kiwi", "apple"], key=len) == ["kiwi", "apple", "banana"]

    # Equal keys keep their relative order (stability).
    stable = [(1, "first"), (0, "zero"), (1, "second"), (0, "zed")]
    assert bubble_sort(stable, key=lambda pair: pair[0]) == [
        (0, "zero"),
        (0, "zed"),
        (1, "first"),
        (1, "second"),
    ]

    # In-place: the returned object is the argument, and it is now ordered.
    original = [3, 1, 2]
    result = bubble_sort(original)
    assert result is original
    assert original == [1, 2, 3]

    # Agreement with the standard library on a fixed pseudo-random sample.
    import random

    random.seed(20240924)
    sample = [random.randint(-100, 100) for _ in range(200)]
    assert bubble_sort(list(sample)) == sorted(sample)
    assert bubble_sort(list(sample), reverse=True) == sorted(sample, reverse=True)


if __name__ == "__main__":
    main()

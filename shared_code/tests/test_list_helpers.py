"""Tests for list helper utilities."""

from pathlib import Path

import pytest
from diskcache import Deque

from shared_code.util.lists import batch_deque, listify, new_list, uniq


def test_new_list_returns_independent_empty_lists() -> None:
    """Callable defaults must not share mutable state."""
    first: list[str] = new_list()
    second: list[str] = new_list()

    first.append("value")

    assert first == ["value"]
    assert second == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("one", ["one"]),
        (["one", "two"], ["one", "two"]),
        (("one", "two"), ["one", "two"]),
    ],
)
def test_listify_normalizes_form_values(value: object, expected: list[object]) -> None:
    """Scalars and supported collections become a list."""
    assert listify(value) == expected


def test_listify_converts_sets_to_lists() -> None:
    """Set input takes the collection path while retaining all values."""
    assert set(listify({"one", "two"})) == {"one", "two"}


def test_uniq_preserves_first_occurrences() -> None:
    """Duplicate values are removed without disturbing their original order."""
    assert uniq(["first", "second", "first", "third", "second"]) == ["first", "second", "third"]


def test_batch_deque_returns_available_items_and_validates_size(tmp_path: Path) -> None:
    """Batching stops cleanly at deque exhaustion and rejects invalid sizes."""
    queue = Deque(directory=tmp_path)
    queue.extend(["first", "second"])

    assert batch_deque(queue, 3) == ["first", "second"]

    with pytest.raises(ValueError, match="at least 1"):
        batch_deque(queue, 0)

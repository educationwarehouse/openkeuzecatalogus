"""Tests for request-data parsing helpers."""

import dataclasses as dc

import pytest
from common.models.request_data import parse_form_data, parse_form_data_with_bracket_notation


@dc.dataclass
class Request:
    """Minimal request double used by the parse_form_data tests."""

    query: dict


def test_parse_form_data_uses_request_query() -> None:
    """Parse request data from the query mapping."""
    request = Request(
        query={
            "user[name]": "Alice",
            "tags[]": ["python", "django"],
        },
    )

    assert parse_form_data(request) == {
        "user": {
            "name": "Alice",
        },
        "tags": ["python", "django"],
    }


def test_parse_form_data_with_bracket_notation_parses_simple_object() -> None:
    """Expand one-level bracket notation into a nested object."""
    data = {
        "user[name]": "Alice",
        "user[email]": "alice@example.com",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "user": {
            "name": "Alice",
            "email": "alice@example.com",
        }
    }


def test_parse_form_data_with_bracket_notation_parses_nested_object() -> None:
    """Expand nested bracket notation into a nested object."""
    data = {
        "user[address][city]": "Amsterdam",
        "user[address][zip]": "1011",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "user": {
            "address": {
                "city": "Amsterdam",
                "zip": "1011",
            }
        }
    }


def test_parse_form_data_with_bracket_notation_parses_simple_list() -> None:
    """Expand a repeated bracket key into a list."""
    data = {
        "tags[]": ["python", "django"],
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "tags": ["python", "django"],
    }


def test_parse_form_data_with_bracket_notation_parses_single_list_value() -> None:
    """Coerce a single bracket-list value into a one-item list."""
    data = {
        "tags[]": "python",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "tags": ["python"],
    }


def test_parse_form_data_with_bracket_notation_parses_list_of_objects() -> None:
    """Expand indexed bracket notation into a list of objects."""
    data = {
        "items[0][name]": "Apple",
        "items[0][qty]": "2",
        "items[1][name]": "Banana",
        "items[1][qty]": "3",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "items": [
            {"name": "Apple", "qty": "2"},
            {"name": "Banana", "qty": "3"},
        ]
    }


def test_parse_form_data_with_bracket_notation_preserves_sparse_list_indexes() -> None:
    """Preserve missing list indexes as None."""
    data = {
        "items[1][name]": "Apple",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "items": [
            None,
            {"name": "Apple"},
        ]
    }


def test_parse_form_data_with_bracket_notation_preserves_non_bracket_keys() -> None:
    """Leave non-bracket keys untouched."""
    data = {
        "csrf_token": "abc123",
        "user[name]": "Alice",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "csrf_token": "abc123",
        "user": {
            "name": "Alice",
        },
    }


def test_parse_form_data_with_bracket_notation_empty_input() -> None:
    """Return an empty mapping for empty input."""
    assert parse_form_data_with_bracket_notation({}) == {}


def test_parse_form_data_with_bracket_notation_appends_single_list_value_flat() -> None:
    """An empty segment appends to the list rather than nesting the submitted value inside it."""
    assert parse_form_data_with_bracket_notation({"tags[]": "python"}) == {"tags": ["python"]}
    assert parse_form_data_with_bracket_notation({"tags[]": ["python", "django"]}) == {
        "tags": ["python", "django"],
    }


def test_parse_form_data_with_bracket_notation_merges_keys_that_alias_one_slot() -> None:
    """Two keys addressing one slot collect their values, in submission order.

    Bracket segments are stripped, so `user[name]` and `user[ name ]` land on the same key.
    This is the only route by which a leaf sees an existing value, so it is what pins down the
    merge behaviour.
    """
    data = {
        "user[name]": "Alice",
        "user[ name ]": "Bob",
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "user": {
            "name": ["Alice", "Bob"],
        },
    }


def test_parse_form_data_with_bracket_notation_merges_list_value_onto_existing_leaf() -> None:
    """Merging a list onto an existing leaf flattens it instead of nesting it."""
    data = {
        "user[name]": "Alice",
        "user[ name ]": ["Bob", "Carol"],
    }

    assert parse_form_data_with_bracket_notation(data) == {
        "user": {
            "name": ["Alice", "Bob", "Carol"],
        },
    }


def test_parse_form_data_with_bracket_notation_merges_equivalent_list_indexes() -> None:
    """Zero-padded indexes address the same slot and merge into one list."""
    data = {
        "items[0]": "a",
        "items[00]": "b",
        "items[000]": "c",
    }

    assert parse_form_data_with_bracket_notation(data) == {"items": [["a", "b", "c"]]}


def test_parse_form_data_with_bracket_notation_rejects_non_numeric_list_segment() -> None:
    """Reject a non-numeric segment where the container is already a list."""
    with pytest.raises(ValueError, match="Unsupported form key segment"):
        parse_form_data_with_bracket_notation({"items[0][a]": "x", "items[b]": "y"})

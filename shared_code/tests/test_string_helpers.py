"""Unit tests for shared string helpers."""

import datetime as dt

import pytest

from shared_code.util.strings import format_preview_value, pluralize, text_block


def test_pluralize_returns_singular_form_with_count() -> None:
    """A count of one should use the singular word and include the count."""
    assert pluralize("apple", 1) == "1 apple"


def test_pluralize_returns_default_plural_form() -> None:
    """Counts other than one should use the default plural suffix."""
    assert pluralize("apple", 2) == "2 apples"


def test_pluralize_uses_custom_plural_form() -> None:
    """An explicit plural form should override the default suffix."""
    assert pluralize("mouse", 3, plural="mice") == "3 mice"


def test_pluralize_can_hide_the_count() -> None:
    """The count can be omitted when only the label is needed."""
    assert pluralize("mouse", 3, plural="mice", hide_count=True) == "mice"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "ja"),
        (False, "nee"),
        ("ongewijzigd", "ongewijzigd"),
        (dt.datetime(2026, 8, 14, 9, 30, 15), "2026-08-14 09:30:15"),
        (dt.date(2026, 8, 14), "2026-08-14"),
        (dt.time(9, 30, 15), "09:30:15"),
        ({"naam": "Methode", "tags": ["nieuw"]}, '{"naam": "Methode", "tags": ["nieuw"]}'),
    ],
)
def test_format_preview_value_formats_import_values_for_display(value: object, expected: str) -> None:
    """Import-preview values retain human-readable values and serialize structured data."""
    assert format_preview_value(value) == expected


def test_text_block_removes_indentation_and_surrounding_blank_lines() -> None:
    """An indented block starting after the opening quotes keeps only its relative layout."""
    text = """
        Eerste alinea
        loopt door.

            Ingesprongen regel.
    """

    assert text_block(text) == "Eerste alinea\nloopt door.\n\n    Ingesprongen regel."


def test_text_block_cleans_text_starting_on_the_opening_line() -> None:
    """Text on the same line as the opening quotes does not prevent dedenting the rest."""
    text = """Eerste regel
        tweede regel
    """

    assert text_block(text) == "Eerste regel\ntweede regel"

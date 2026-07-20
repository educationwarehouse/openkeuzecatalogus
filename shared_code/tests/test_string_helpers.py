"""Unit tests for shared string helpers."""

from shared_code.util.strings import pluralize


def test_pluralize_returns_singular_form_with_count() -> None:
    """A count of one should use the singular word and include the count."""
    assert pluralize("apple", 1) == "1 apple"


def test_pluralize_returns_default_plural_form() -> None:
    """Counts other than one should use the default plural suffix."""
    assert pluralize("apple", 2) == "2 apples"


def test_pluralize_uses_custom_plural_form() -> None:
    """An explicit plural form should override the default suffix."""
    assert pluralize("mouse", 3, "mice") == "3 mice"


def test_pluralize_can_hide_the_count() -> None:
    """The count can be omitted when only the label is needed."""
    assert pluralize("mouse", 3, "mice", hide_count=True) == "mice"

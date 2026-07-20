"""Tests for UUID representer helpers."""

from uuid import UUID

from shared_code.data_model.representers.uuid import short_uuid


def test_short_uuid_renders_uuid_value_and_clipboard_behavior() -> None:
    """Render the UUID into a clickable clipboard icon with a hidden field."""
    gid = UUID("12345678-1234-5678-1234-567812345678")

    rendered = str(short_uuid(gid))

    assert str(gid) in rendered
    assert "fa-clipboard" in rendered
    assert "center-in-cell" in rendered
    assert "text-success" in rendered
    assert "navigator.clipboard.writeText" in rendered
    assert "gid" in rendered


def test_short_uuid_accepts_string_input_and_renders_same_uuid_text() -> None:
    """String UUID inputs should render the same copied value."""
    gid = "12345678-1234-5678-1234-567812345678"

    rendered = str(short_uuid(gid))

    assert gid in rendered

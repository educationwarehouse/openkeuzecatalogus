"""Tests for markdown mixin setup and rendering."""

from yatl import XML

from shared_code.data_model.mixins.markdown import MarkdownMixin


class DemoMarkdown(MarkdownMixin):
    """Minimal class for exercising `MarkdownMixin` behavior."""

    def __init__(self) -> None:
        """Initialize with one markdown-enabled field."""
        self.body = "**hello**"


def test_markdown_mixin_sets_markdown_converter_on_subclass() -> None:
    """Ensure subclass creation sets up a markdown converter."""
    assert hasattr(DemoMarkdown, "md")
    assert callable(DemoMarkdown.md.convert)


def test_markdown_mixin_converts_markdown_to_xml() -> None:
    """Ensure markdown conversion returns XML output."""
    item = DemoMarkdown()
    rendered = item.markdown("body")

    assert isinstance(rendered, XML)
    assert "<strong>hello</strong>" in str(rendered)


def test_markdown_mixin_escapes_raw_html() -> None:
    """Ensure raw HTML input is rendered inert."""

    class DemoUnsafeMarkdown(MarkdownMixin):
        """Minimal class for exercising unsafe markdown input."""

        def __init__(self) -> None:
            self.body = "**hello** <script>alert(1)</script>"

    rendered = DemoUnsafeMarkdown().markdown("body")

    assert "<strong>hello</strong>" in str(rendered)
    assert "<script>" not in str(rendered)
    assert "&lt;script&gt;" in str(rendered)

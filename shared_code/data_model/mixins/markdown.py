"""Mixin helpers for rendering markdown fields as HTML."""

import html
import typing as t

from markdown2 import Markdown
from typedal.mixins import Mixin

if t.TYPE_CHECKING:
    from yatl import XML


class MarkdownMixin(Mixin):
    """Mixin to convert markdown to HTML without adding table fields."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Initialize subclass markdown converter state."""
        # mixins don't have __init__ or instance variables,
        # only init subclass and cls variables!
        cls.md = Markdown()
        super().__init_subclass__(**kwargs)

    def markdown(self, field: str) -> XML:
        """Convert a markdown field to HTML.

        Args:
            field: Field name to convert.

        """
        from yatl import XML

        data = getattr(self, field)
        # Escape raw HTML before conversion so markdown formatting still works
        # while untrusted tags are rendered inert.
        safe_data = html.escape(str(data or ""))
        return XML(self.md.convert(safe_data))

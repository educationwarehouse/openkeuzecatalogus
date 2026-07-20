"""Reusable action button helpers for grid rendering."""

import typing as t

BUTTON_CLASS = "btn btn-sm btn-secondary"


class GridActionButton:
    """Container for grid action button rendering details."""

    def __init__(
        self,
        text: str,
        url: str,
        icon: str | None = None,
        additional_classes: t.Iterable[str] = (BUTTON_CLASS, "grid-button"),
        additional_styles: str = "",
        override_classes: str = "",
        override_styles: str = "",
        message: str = "",
        append_id: bool = False,
        name: str | None = None,
        ignore_attribute_plugin: bool = False,
        **attrs: t.Any,
    ) -> None:
        """Store the arguments needed to render an action button."""
        self.url = url
        self.text = text
        self.icon = icon
        self.additional_classes = " ".join(additional_classes)
        self.additional_styles = additional_styles
        self.override_classes = override_classes
        self.override_styles = override_styles
        self.message = message
        self.append_id = append_id
        self.name = name
        self.ignore_attribute_plugin = ignore_attribute_plugin
        self.attrs = attrs

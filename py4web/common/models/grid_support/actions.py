"""Reusable action button helpers for grid rendering."""

import json
import typing as t
from urllib.parse import parse_qsl, unquote, urlsplit

from yatl import FORM, SPAN, A, I
from yatl import TAGGER as HTMLElement
from yatl.helpers import BUTTON

from common.constants import BUTTON_CLASS
from common.models.backend.session import grid_action_signer
from py4web import URL
from shared_code.util.html import convert_attrs


def signed_post_action_url(url: str) -> str:
    """Bind a local grid action target to the current session."""
    target = urlsplit(url)

    if target.scheme or target.netloc or not target.path.startswith("/"):
        raise ValueError("POST grid actions require a local absolute path")

    return URL(
        unquote(target.path),
        vars=dict(parse_qsl(target.query)),
        signer=grid_action_signer,
        use_appname=False,
    )


def post_action_form(button: HTMLElement, url: str, message: str = "") -> HTMLElement:
    """Wrap a submit button in a session-signed POST form."""
    if message:
        button["_onclick"] = f"if(!confirm({json.dumps(message)})) return false;"

    return FORM(button, _action=signed_post_action_url(url), _method="POST", _class="grid-action-form")


class GridActionButton:
    """Grid action rendered as a link or a session-signed POST button.

    POST endpoints must use ``method="POST"`` and the ``grid_action_verified`` fixture.
    """

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
        method: t.Literal["GET", "POST"] = "GET",
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
        self.method = method
        self.attrs = attrs
        self.param = None

    def bind_param(self, param: t.Any) -> None:
        """Bind grid.param when grid is being constructed."""
        self.param = param

    def get_param_value[T](self, key: str, default: T) -> T:
        """Get a key from 'grid.param' that may or may not exist."""
        if not self.param:
            return default

        return getattr(self.param, key, default)


class GridHeaderButton(GridActionButton):
    """Represents a button element used in grid headers or footers."""

    def __call__(self) -> HTMLElement:
        """This allows using the element as a header/footer element.

        note that it uses only a subset of options that GridActionButton provides.

        header_elements=[
            GridHeaderButton( ...
        """
        class_style = (
            {"_class": self.override_classes}
            if self.override_classes
            else self.get_param_value("grid_class_style", {}).get("grid-header-button", {})
        )

        element = BUTTON if self.method == "POST" else A
        attrs = {"type": "submit"} if self.method == "POST" else {"href": self.url}

        button = element(
            SPAN(
                I(_class=f"fas {self.icon} px-1") if self.icon else None,
                SPAN(self.text, _class="px-1"),
                **class_style,
            ),
            _class="grid-new-button ms-3",
            **convert_attrs(attrs),
        )

        if self.method == "POST":
            return post_action_form(button, self.url, message=self.message)
        else:
            return button

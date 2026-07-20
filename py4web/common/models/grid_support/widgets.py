"""Typed widget helpers for the admin grid support forms."""

import typing as t

from py4web.utils.form import FormStyleFactory as FormStyle
from py4web.utils.form import Widget, join_classes
from typedal import TypedField
from yatl import TAGGER as HTMLElement
from yatl.helpers import (
    BUTTON,
    DIV,
    INPUT,
    TAG,
    XML,
)

from py4web import Field

TEMPLATE = TAG.template
B = TAG.b
SMALL = TAG.small


class EddieWidget(Widget):
    """Widget base class that adds form-style awareness."""

    formstyle: FormStyle | None = None

    def set_form_style(self, formstyle: FormStyle) -> None:
        """Store the form style used when rendering controls."""
        self.formstyle = formstyle

    def apply_style(self, control: HTMLElement) -> None:
        """Apply the configured form-style classes to a control."""
        if self.formstyle:
            # patch input classes:
            # (source: py4web/utils/form.py:468
            key = control.name.rstrip("/")

            if key == "input":
                key += "[type=%s]" % (control["_type"] or "text")

            control["_class"] = join_classes(control.attributes.get("_class"), self.formstyle.classes.get(key))

    @classmethod
    def field_to_id(cls, field: str | Field | TypedField) -> str:
        """Convert a field reference to a stable DOM id fragment."""
        return str(field).replace(".", "_")

    def make(
        self, field: Field, value: t.Any, error: str, title: str, placeholder: str = "", readonly: bool = False
    ) -> HTMLElement:
        """Delegate to the default widget renderer with typed arguments."""
        # this 'implementation' just adds typing and passes it back to the default Widget.make
        return super().make(field, value, error, title, placeholder=placeholder, readonly=readonly)


class EddieListWidget(EddieWidget):
    """Widget that renders add/remove rows for semicolon-separated values."""

    def make_row(
        self, name: str, value: str | None, idx: int, placeholder: str | None, readonly: bool = False
    ) -> HTMLElement:
        """Render one row in the editable list widget."""
        return DIV(
            DIV(
                INPUT(_name=name, _value=value, _class="form-control", _placeholder=placeholder, readonly=readonly),
                BUTTON(
                    XML("-"),
                    _type="button",
                    _class="btn btn-outline-danger",
                    __="on click set parent to closest .list-widget-item then call parent's remove()",
                )
                if idx > 0
                else "",
                _class="input-group mb-2",
            ),
            _class="list-widget-item",
        )

    def make(
        self, field: Field, value: t.Any, error: str, title: str, placeholder: str = "", readonly: bool = False
    ) -> HTMLElement:
        """Render the full editable list widget."""
        values = value or []
        if isinstance(values, str):
            values = [_.strip() for _ in values.split(";")]

        inputs = []
        for idx, value in enumerate(values or [""]):
            inputs.append(self.make_row(field.name, value, idx, placeholder, readonly=readonly))

        # hash to prevent collisions:
        template_id = f"{field.name}_template_{hash(self)}"
        inputs_id = f"{field.name}_inputs_{hash(self)}"

        add_button = BUTTON(
            XML("&plus;"),
            _type="button",
            _id="add-btn",
            _class="btn btn-primary",
            _style="margin-top: 5px;",
            __=f"""
                on click
                    -- create new row by duplicating template html:
                    set tmpl to #{template_id}'s innerHTML
                    -- add html to input holder:
                    -- (`put` works better than `append`)
                    put tmpl as HTML at the end of #{inputs_id}
                    -- update hyperscript (onclick) callbacks on input holder:
                    call _hyperscript.processNode(#{inputs_id})
                """,
        )
        return DIV(
            DIV(*inputs, _id=inputs_id),
            TEMPLATE(self.make_row(field.name, None, 1, placeholder, readonly=readonly), _id=template_id),
            add_button,
            _id=f"list-widget-{field.name}",
            _class="card card-body",
        )


class WidgetProtocol(t.Protocol):
    """Protocol for widgets that can render a form field."""

    def make(
        self, field: Field, value: t.Any, error: str, title: str, placeholder: str = "", readonly: bool = False
    ) -> HTMLElement:
        """Render a field control for the given form inputs."""
        ...


class ReadonlyWidget(EddieWidget):
    """Render a widget in read-only mode while preserving its base styling."""

    def __init__(self, reason: str = "", initial: EddieWidget | None = None) -> None:
        """Store the read-only explanation and optional base widget."""
        self.reason = reason
        self.initial = initial

    @staticmethod
    def find_initial(field: Field) -> WidgetProtocol:
        """Choose the closest matching widget for a field's declared type."""
        # py4web/utils/form.py:425
        from py4web.utils.form import (
            CheckboxWidget,
            DateTimeWidget,
            FileUploadWidget,
            ListWidget,
            PasswordWidget,
            SelectWidget,
            TextareaWidget,
            get_options,
        )

        if field.type == "text":
            return TextareaWidget()
        elif field.type == "datetime":
            return DateTimeWidget()
        elif field.type == "boolean":
            return CheckboxWidget()
        elif field.type == "upload":
            return FileUploadWidget()
        elif get_options(field.requires) is not None:
            return SelectWidget()
        elif field.type == "password":
            return PasswordWidget()
        elif str(field.type).startswith("list:"):
            return ListWidget()
        else:
            return Widget()

    def make(
        self, field: Field, value: t.Any, error: str, title: str, placeholder: str = "", readonly: bool = False
    ) -> HTMLElement:
        """Render a read-only control wrapped with a short explanatory note."""
        # control = super().make(field, value, error, title, placeholder=placeholder, readonly=True)
        widget = self.initial or self.find_initial(field)
        control = widget.make(field, value, error, title, placeholder=placeholder, readonly=True)

        self.apply_style(control)
        # disable pointer events, set opacity:
        control["_class"] = join_classes(control.attributes.get("_class"), "disabled")

        return DIV(control, SMALL(self.reason), _style="display: inline")

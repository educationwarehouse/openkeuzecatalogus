"""Typed widget helpers for the admin grid support forms."""

import json
import typing as t
import uuid

from py4web.utils.form import FormStyleFactory as FormStyle
from py4web.utils.form import Widget, join_classes
from pydal.objects import Table
from pydal.validators import IS_IN_SET
from typedal import TypedField, TypedTable
from typedal.types import Expression, Validator
from yatl import TAGGER as HTMLElement
from yatl.helpers import (
    BUTTON,
    DIV,
    INPUT,
    LABEL,
    SCRIPT,
    SPAN,
    TAG,
    XML,
    A,
)

from py4web import Field
from shared_code.data_model import AnyDict
from shared_code.util.html import convert_attrs
from shared_code.util.lists import listify
from shared_code.util.types import MultiValue

TEMPLATE = TAG.template
B = TAG.b
SMALL = TAG.small


class EddieWidget(Widget):
    """Widget base class that adds form-style awareness."""

    formstyle: FormStyle | None = None

    @staticmethod
    def find_initial(field: Field) -> Widget:
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

        if field.type in ("text", "json"):
            inner = TextareaWidget()
        elif field.type == "datetime":
            inner = DateTimeWidget()
        elif field.type == "boolean":
            inner = CheckboxWidget()
        elif field.type == "upload":
            inner = FileUploadWidget()
        elif get_options(field.requires) is not None:
            inner = SelectWidget()
        elif field.type == "password":
            inner = PasswordWidget()
        elif str(field.type).startswith("list:"):
            inner = ListWidget()
        else:
            inner = Widget()

        return t.cast(Widget, inner)

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
    def field_to_id(cls, field: str | Field | TypedField | Expression) -> str:
        """Convert a field reference to a stable DOM id fragment."""
        return str(field).replace(".", "_")

    def make(
        self,
        field: Field,
        value: t.Any,
        error: str,
        title: str,
        placeholder: str = "",
        readonly: bool = False,
    ) -> HTMLElement:
        """Delegate to the default widget renderer with typed arguments."""
        # this 'implementation' just adds typing and passes it back to the default Widget.make
        return super().make(field, value, error, title, placeholder=placeholder, readonly=readonly)


class ShowIfWidget(EddieWidget):
    """Simple replacement for web2py's show_if functionality.

    Supports boolean (checkbox) fields and dropdowns with specific values.

    ~field is supported to inverse logic for boolean fields.
    For dropdowns, specify the values to match using only_if or unless parameters.
    """

    def __init__(
        self,
        field: str | Field | TypedField | Expression,
        inner: type[Widget] | Widget | None = None,
        only_if: MultiValue[str] | None = None,
        unless: MultiValue[str] | None = None,
        required: bool = False,
    ) -> None:
        """Initialize a ShowIfWidget.

        Args:
            field: The field to depend on (checkbox or dropdown)
            inner: The widget to show/hide (defaults to the field's natural widget)
            only_if: For dropdowns, show inner widget only if field value is in this list
            unless: For dropdowns, show inner widget unless field value is in this list
            required: Whether the target input is required when visible

        """
        # if field is ~field, do something else:
        if isinstance(field, Expression) and getattr(field, "op", None):
            self.invert = field.op.__name__ == "invert"
            field = t.cast(Expression, field.first)
        else:
            self.invert = False

        self.source_name = getattr(field, "name", str(field).split(".")[-1])
        self.depends_on = self.field_to_id(field)
        self.inner = inner() if isinstance(inner, type) else inner
        self.only_if = tuple(only_if) if only_if is not None else None
        self.unless = tuple(unless) if unless is not None else None
        self.required = required

    def make(
        self,
        field: Field,
        value: t.Any,
        error: str,
        title: str,
        placeholder: str = "",
        readonly: bool = False,
    ) -> HTMLElement:
        """Wrap the control with its dynamic visibility and required behavior."""
        target_id = self.field_to_id(field)
        wrapper_id = f"show_if_{target_id}"

        # actual input:
        inner = self.inner or self.find_initial(field)
        if self.formstyle and hasattr(inner, "set_form_style"):
            inner.set_form_style(self.formstyle)  # type: ignore
        control = inner.make(field, value, error, title, placeholder=placeholder, readonly=readonly)

        self.apply_style(control)

        # Determine the widget type and condition logic based on parameters
        if self.only_if or self.unless:
            # Dropdown logic
            condition_js = self._dropdown_condition_js()
        else:
            # Checkbox logic (original behavior)
            condition_js = "invert ? !$source.checked : $source.checked"

        wrapper_cls = SPAN if field.type == "boolean" else DIV
        wrapper_kwargs: dict[str, str] = {"_id": wrapper_id}
        if field.type == "boolean":
            wrapper_kwargs["_style"] = "display: inline"

        return wrapper_cls(
            control,
            SCRIPT(
                """{
                    function hide($elt, show = false) {
                        if (!$elt) {
                            return;
                        }
                        $elt.style.display = show ? '' : 'none';
                        $elt.hidden = !show;
                    }

                    addEventListener("load", (_) => {
                        const $source = document.querySelector(
                            'input[name="%(source_name)s"], select[name="%(source_name)s"]'
                        );
                        const $target_holder = document.getElementById('%(target_id)s');
                        const $target = $target_holder
                            ? ($target_holder.closest('.form-group, .field') || $target_holder)
                            : null;
                        const $input = $target ? $target.querySelector('input, select, textarea') : null;
                        const invert = %(invert)s;

                        if (!$source) {
                            console.error('element not found', 'name=%(source_name)s');
                            return;
                        }

                        // Helper function to determine visibility based on conditions
                        function evaluate_visibility() {
                            // For dropdown, check if a value is selected at all
                            if ($source && $source.tagName === 'SELECT' && (!$source.value || $source.value === '')) {
                                return false;
                            }
                            return %(condition_js)s;
                        }

                        function update_visibility() {
                            const show = evaluate_visibility();
                            hide($target, show);
                            if ($input) {
                                $input.required = show && %(required)s;
                            }
                        }

                        update_visibility();
                        $source.addEventListener('change', update_visibility);
                    });
                }"""  # noqa UP031 - fstring does not work well with javascript { braces
                % {
                    "source_name": self.source_name,
                    "target_id": wrapper_id,
                    "invert": int(self.invert),
                    "condition_js": condition_js,
                    "required": str(self.required).lower(),
                },
            ),
            **wrapper_kwargs,
        )

    def _dropdown_condition_js(self) -> str:
        """Generate the JavaScript condition for dropdown fields."""
        js_condition = []

        if self.only_if:
            values_json = json.dumps(list(self.only_if))
            js_condition.append(f"$source && ({values_json}.includes($source.value))")

        if self.unless:
            values_json = json.dumps(list(self.unless))
            js_condition.append(f"$source && (!{values_json}.includes($source.value))")

        if js_condition:
            return " && ".join(js_condition)
        else:
            # Fallback to checkbox behavior if neither only_if nor unless is specified
            return "invert ? !$source.checked : $source.checked"


class EddieListWidget(EddieWidget):
    """Widget that renders add/remove rows for semicolon-separated values."""

    def make_row(
        self,
        name: str,
        value: str | None,
        idx: int,
        placeholder: str | None,
        readonly: bool = False,
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
        self,
        field: Field,
        value: t.Any,
        error: str,
        title: str,
        placeholder: str = "",
        readonly: bool = False,
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


class ReadonlyWidget(EddieWidget):
    """Render a widget in read-only mode while preserving its base styling."""

    def __init__(self, reason: str = "", initial: EddieWidget | None = None) -> None:
        """Store the read-only explanation and optional base widget."""
        self.reason = reason
        self.initial = initial

    def make(
        self,
        field: Field,
        value: t.Any,
        error: str,
        title: str,
        placeholder: str = "",
        readonly: bool = False,
    ) -> HTMLElement:
        """Render a read-only control wrapped with a short explanatory note."""
        # control = super().make(field, value, error, title, placeholder=placeholder, readonly=True)
        widget = self.initial or self.find_initial(field)
        control = widget.make(field, value, error, title, placeholder=placeholder, readonly=True)

        self.apply_style(control)
        # disable pointer events, set opacity:
        control["_class"] = join_classes(control.attributes.get("_class"), "disabled")

        return DIV(control, SMALL(self.reason), _style="display: inline")


def extract_is_in_set_options(
    field: TypedField,
) -> dict[str, str] | t.Iterable[str] | None:
    """Extract option values from an `IS_IN_SET` validator."""
    requires = [field.requires] if not isinstance(field.requires, t.Iterable) else field.requires
    for requirement in requires:
        if not isinstance(requirement, IS_IN_SET):
            continue
        return requirement.theset
    return None


class SingleSelectWidget:
    """Render a single-value dropdown backed by a hidden form input."""

    def __init__(
        self,
        name: str | TypedField[str],
        options: dict[str, str] | t.Iterable[str] = (),
        _id: str | None = None,
        default: str | None = None,
        placeholder: str = "Selecteer een optie",
        order: bool = True,
        readonly: bool = False,
    ) -> None:
        """Initialize a single-select widget and resolve field options."""
        if not isinstance(options, dict):
            options = tuple(options)

        if isinstance(name, str):
            self.field = None
            self.name = name
            self.default = default
        else:
            self.field = name
            self.name = name.name
            if (
                not options
                and self.field.requires
                and (requires_set := extract_is_in_set_options(self.field)) is not None
            ):
                options = requires_set if isinstance(requires_set, dict) else tuple(requires_set)

            self.default = name.default if default is None else default

        self.options = options
        self.placeholder = placeholder
        self.order = order
        self.readonly = readonly
        self.id = _id or f"{self.name}-{uuid.uuid4()}"

    def __call__(self, _: Table | type[TypedTable], data: AnyDict) -> HTMLElement:
        """Render the dropdown and its current form value."""
        raw_current = data.get(self.name)
        if raw_current in (None, "") and self.default not in (None, ""):
            raw_current = self.default

        current_value = "" if raw_current in (None, "") else str(raw_current)
        readonly = self.readonly

        if isinstance(self.options, dict):
            items = [(str(key), str(label)) for key, label in self.options.items() if key not in (None, "")]
        else:
            items = [(str(value), str(value)) for value in self.options if value not in (None, "")]

        if self.order:
            items.sort(key=lambda kv: kv[1].lower())

        selected_label = current_value
        if not selected_label:
            selected_label = self.placeholder

        dropdown_items = []
        for value, label in items:
            selected = value == current_value
            if selected:
                selected_label = label

            dropdown_items.append(
                A(
                    SPAN(label, _class="item-label"),
                    _href="#",
                    **convert_attrs(
                        {
                            "class": f"dropdown-item{' selected' if selected else ''}",
                            "data-value": value,
                            "role": "option",
                            "tabindex": "0",
                        },
                    ),
                ),
            )

        button = BUTTON(
            SPAN(selected_label, _class="selected-text"),
            "" if readonly else SPAN("", _class="dropdown-icon"),
            **convert_attrs(
                {
                    "class": "btn btn-brand btn-brand-hollow dropdown-toggle " + ("disabled" if readonly else ""),
                    "type": "button",
                    "data-bs-toggle": "dropdown",
                    "data-bs-auto-close": "outside",
                    "aria-expanded": "false",
                    "aria-label": self.placeholder,
                },
            ),
        )

        dropdown_menu = DIV(
            *dropdown_items,
            **convert_attrs(
                {
                    "class": "dropdown-menu capsule-dropdown-menu",
                    "role": "listbox",
                },
            ),
        )

        return DIV(
            button,
            "" if readonly else dropdown_menu,
            INPUT(
                _type="hidden",
                _name=self.name,
                _value=current_value,
                _autocomplete="off",
            ),
            **convert_attrs(
                {
                    "class": "capsule-dropdown",
                    "data-widget": "single-select",
                    "id": f"{self.id}-capsule",
                    "data-placeholder": self.placeholder,
                },
            ),
        )


class MultipleSelectWidget:
    """Render a multi-value checkbox dropdown backed by form inputs."""

    def __init__(
        self,
        name: str | TypedField[list[str]],
        options: dict[str, str] | t.Iterable[str] = (),
        _id: str | None = None,
        default: list[str] | None = None,
        placeholder: str = "Selecteer één of meer opties",
        order: bool = True,
        readonly: bool = False,
    ) -> None:
        """Initialize a multi-select widget and resolve field options."""
        if not isinstance(options, dict):
            options = tuple(options)

        if isinstance(name, str):
            self.field = None
            self.name = name
            self.default = default or []
        else:
            self.field = name
            self.name = name.name
            if (
                not options
                and self.field.requires
                and (requires_set := extract_is_in_set_options(self.field)) is not None
            ):
                options = requires_set if isinstance(requires_set, dict) else tuple(requires_set)

            self.default = name.default if default is None else default

        self.options = options  # optional when using requires=IS_IN_SET
        self.placeholder = placeholder
        self.order = order
        self.readonly = readonly

        self.id = _id or f"{self.name}-{uuid.uuid4()}"

    def __call__(self, _: Table | type[TypedTable], data: AnyDict) -> HTMLElement:
        """Render the checkbox dropdown and its current selections."""
        current = listify(data.get(self.name) or self.default or [])
        current_values = {str(value) for value in current}

        readonly = self.readonly

        if isinstance(self.options, dict):
            options = t.cast(
                dict[str, tuple[str, bool]],
                {key: (value, str(key) in current_values) for key, value in self.options.items() if key},
            )
        else:
            options = {value: (value, str(value) in current_values) for value in self.options}

        selected_labels = [label for label, selected in options.values() if selected]

        selected_text = ", ".join(selected_labels) if selected_labels else self.placeholder
        selected_count_text = f"{len(selected_labels)} selected"

        iterator = sorted(options.items(), key=lambda k_v: k_v[1][0]) if self.order else options.items()

        dropdown_items = []
        for value, (label, selected) in iterator:
            option_id = f"{self.name}-{hash(value)}"
            dropdown_items.append(
                SPAN(
                    INPUT(
                        _name=self.name,
                        _id=option_id,
                        _type="checkbox",
                        _class="form-check-input",
                        _checked=selected,
                        _value=value,
                        _tabindex="-1",  # Make checkbox not directly focusable, label will handle focus
                    ),
                    LABEL(label, _class="item-label", _for=option_id),
                    **convert_attrs(
                        {
                            "class": f"dropdown-item d-flex align-items-center{' selected' if selected else ''}",
                            "role": "option",
                            # JS will handle aria-selected
                            "data-search": f"{label.lower().strip()} {value.lower().strip()}",
                        },
                    ),
                ),
            )

        container_id = f"{self.id}-capsule"

        search_input = INPUT(
            **convert_attrs(
                {
                    "type": "search",
                    "class": "capsule-search-input",
                    "placeholder": "Zoek...",
                    "aria-label": "Zoek opties",
                },
            ),
        )

        dropdown_menu = DIV(
            DIV(
                search_input,
                _class="capsule-search-container",
            ),
            DIV(
                *dropdown_items,
                _class="search-results",
            ),
            DIV(
                SPAN(selected_count_text, _class="selected-count small"),
                BUTTON(
                    "Done",
                    _type="button",
                    _class="close-dropdown-btn",
                ),
                _class="capsule-dropdown-footer",
            ),
            **convert_attrs(
                {
                    "class": "dropdown-menu capsule-dropdown-menu",
                    "role": "listbox",
                    "aria-multiselectable": "true",
                },
            ),
        )

        button = BUTTON(
            SPAN(selected_text, _class="selected-text"),
            "" if readonly else SPAN("", _class="dropdown-icon"),
            **convert_attrs(
                {
                    "class": "btn btn-brand btn-brand-hollow dropdown-toggle " + ("disabled" if readonly else ""),
                    "type": "button",
                    "data-bs-toggle": "dropdown",
                    "data-bs-auto-close": "outside",
                    "aria-expanded": "false",
                    "aria-label": self.placeholder,
                },
            ),
        )

        return DIV(
            DIV(
                button,
                "" if readonly else dropdown_menu,
                **convert_attrs(
                    {
                        "class": "capsule-dropdown",
                        "data-widget": "multi-select",
                        "id": container_id,
                        "data-placeholder": self.placeholder,
                    },
                ),
            ),
        )


def use_multiselect(field: TypedField[list[str]], options: t.Iterable[str] | None = None) -> None:
    """Render one `list:string` field as a searchable multi-select over `options`.

    Both halves are required. `IS_IN_SET(multiple=True)` is what makes py4web keep every
    ticked box: the form reads one value per field name (`utils/form.py:894`) and hands it to
    the validator, which normalises a scalar or a list into a list. Without it only the last
    checkbox would survive. `MultipleSelectWidget` is then what renders the boxes at all.

    `default=[]` because the field's own default is the `new_list` factory; the widget reads
    `field.default` as a value, so it would otherwise put a function object in the selection.
    """
    if options is not None:
        field.requires = t.cast(list[Validator], [IS_IN_SET(sorted(options), multiple=True)])
    field.widget = MultipleSelectWidget(field, default=[])

"""Grid and form styles for EddieGrid."""

import typing as t
from copy import deepcopy

import pydal.validators
from py4web.utils.auth import Auth
from py4web.utils.form import Form, FormStyleBootstrap4, FormStyleFactory
from py4web.utils.grid import GridClassStyleBootstrap5
from typedal import TypedTable
from yatl.helpers import XML

from common.models import auth
from shared_code.data_model import AnyDict

from .actions import BUTTON_CLASS
from .py4web_grid import clean_sc


class EddieGridStyle(GridClassStyleBootstrap5):
    """Bootstrap grid class-style overrides used by EddieGrid."""

    classes = {
        # todo: check with proper bootstrap 5.3
        "grid-wrapper": "grid-wrapper",
        "grid-header": "grid-header clearfix pb-2",
        "grid-new-button": "grid-new-button btn btn-outline-primary",
        "grid-search": "grid-search float-end pb-2",
        "grid-table-wrapper": "grid-table-wrapper table-responsive",
        "grid-table": "grid-table table table-striped table-hover table-bordered clearfix",
        "grid-sorter-icon-up": "grid-sort-icon-up fas fa-sort-up float-end",
        "grid-sorter-icon-down": "grid-sort-icon-down fas fa-sort-down float-end",
        "grid-thead": "",
        "grid-tr": "",
        "grid-th": "small",
        "grid-td": "small",
        "grid-td-buttons": "grid-td-buttons",
        "grid-button": f"grid-button {BUTTON_CLASS}",
        "grid-details-button": f"grid-details-button {BUTTON_CLASS}",
        "grid-edit-button": f"grid-edit-button {BUTTON_CLASS}",
        "grid-delete-button": f"grid-delete-button {BUTTON_CLASS}",
        "grid-search-button": "grid-search-button btn btn-outline-info",
        "grid-clear-button": "grid-clear-button btn btn-outline-info",
        "grid-footer": "grid-footer pb-4",
        "grid-info": "grid-info float-start",
        "grid-pagination": "grid-pagination float-end",
        "grid-pagination-button": "grid-pagination-button btn btn-sm btn-outline-primary",
        "grid-pagination-button-current": "grid-pagination-button-current btn btn-primary btn-sm",
        "grid-cell-type-string": "grid-cell-type-string",
        "grid-cell-type-text": "grid-cell-type-text",
        "grid-cell-type-boolean": "grid-cell-type-boolean text-center",
        "grid-cell-type-float": "grid-cell-type-float",
        "grid-cell-type-decimal": "grid-cell-type-decimal",
        "grid-cell-type-int": "grid-cell-type-int",
        "grid-cell-type-date": "grid-cell-type-date",
        "grid-cell-type-time": "grid-cell-type-time",
        "grid-cell-type-datetime": "grid-cell-type-datetime",
        "grid-cell-type-upload": "grid-cell-type-upload",
        "grid-cell-type-list": "grid-cell-type-list",
        "grid-cell-type-id": "grid-cell-type-id text-center",
        # specific for custom form
        "grid-search-form": "grid-search-form float-end pb-2",
        "grid-search-form-table": "grid-search-form-table",
        "grid-search-form-tr": "grid-search-form-tr",
        "grid-search-form-td": "grid-search-form-td pe-1",
        "grid-search-form-input": "grid-search-form-input form-control",
        "grid-search-form-select": "grid-search-form-select form-select",
        "grid-search-boolean": "grid-search-boolean",
        "grid-header-element": "grid-header-element btn btn-sm",
        "grid-footer-element": "grid-footer-element btn btn-sm",
        "grid-header-button": "btn btn-secondary",
    }

    # 'styles' should not be used anymore (but still in here because grid depends on it)
    styles = {}

    extras = {
        "grid-footer": {
            "hx-swap-oob": "innerhtml:.grid-footer",
        }
    }

    @classmethod
    def get(cls, element: str, default: str = "") -> dict[str, str]:
        """Returns a dict with _class and _style for the element name."""
        extras = {f"_{k}": v for k, v in cls.extras.get(element, {}).items()}

        return clean_sc(_class=cls.classes.get(element, default), **extras)


class EddieFormStyleFactory(FormStyleFactory):
    """Form style factory that marks required fields with a red asterisk."""

    REQUIRED_VALIDATOR_TYPES = frozenset(
        (
            pydal.validators.IS_EMAIL,
            pydal.validators.IS_IN_SET,
            pydal.validators.IS_NOT_EMPTY,
            pydal.validators.IS_IN_DB,
            pydal.validators.IS_STRONG,
            pydal.validators.IS_URL,
        )
    )

    def __init__(self) -> None:
        """Initialize the factory with Bootstrap 4 defaults and exceptions."""
        super().__init__()
        self.classes.update(FormStyleBootstrap4.classes)
        self.class_inner_exceptions = FormStyleBootstrap4.class_inner_exceptions

    def __call__(
        self,
        table: TypedTable,
        vars: AnyDict,
        errors: AnyDict,
        readonly: bool,
        deletable: bool,
        showreadonly: bool,
        show_id: bool,
        kwargs: AnyDict | None = None,
    ) -> t.Any:
        """Render a form while visually marking required fields."""
        # fields having these should be marked as required with a red *

        for field in table:
            if not (field.required or field.requires):
                continue

            requires = field.requires
            if not isinstance(requires, (list, tuple)):
                requires = [requires]

            # Get the set of validator types used in this field
            validator_types = {type(validator) for validator in requires}

            # Check if any of the validator types are in the required set:
            if field.required or any(validator_types & self.REQUIRED_VALIDATOR_TYPES):
                # field is (probably) required, add a red * to indicate this:
                field.label = XML(f"{field.label} <span style='color: red'>*</span>")

        return super().__call__(
            table=table,
            vars=vars,
            errors=errors,
            readonly=readonly,
            deletable=deletable,
            showreadonly=showreadonly,
            show_id=show_id,
            kwargs=kwargs,
        )

    def bind_auth(self, _auth: Auth) -> None:
        """Bind this form style to an auth instance."""
        _auth.param.formstyle = self


EddieFormStyle = EddieFormStyleFactory()
EddieFormStyle.bind_auth(auth)


class EddieForm(Form):
    """Form subclass that uses the Eddie form style by default."""

    def __init__(
        self,
        table: TypedTable,
        **kw: t.Any,
    ) -> None:
        """Initialize a form with the Eddie style as the default formstyle."""
        kw["formstyle"] = deepcopy(kw.get("formstyle") or EddieFormStyle)
        super().__init__(table, **kw)

"""EddieGrid runtime orchestration."""

import functools
import traceback
import typing as t
import warnings
from collections.abc import Mapping
from copy import deepcopy

from py4web.utils.form import Form
from py4web.utils.grid import parse_referrer
from typedal import TypeDAL, TypedField, TypedRows
from typedal.tables import TableMeta
from typedal.types import Field, Query, Row
from yatl import TAGGER as HTMLElement
from yatl.helpers import DIV

from common.models import auth, backend
from py4web import HTTP, URL, redirect, request
from shared_code.data_model import AnyDict, update_effectivedated
from shared_code.data_model.mixins.effdt import EffdtTable, ed_restore_by_id, latest_ed, model_to_ed
from shared_code.data_model.representers.uuid import short_uuid
from shared_code.data_model.tables import BaseTable
from shared_code.data_model.tables.base import TableWithGid
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.util.class_utils import class_deepcopy

from .actions import BUTTON_CLASS, GridActionButton, GridHeaderButton
from .archive import build_archive_table
from .json_import import JsonImport, JsonImportConfig
from .py4web_grid import (
    AFTER_LAST_FIELD,
    ExtraFormHtml,
    ExtraFormHtmlItem,
    FormWithParam,
    Grid,
    GridButtons,
    GridColumns,
    GridGroupBy,
    GridHeaderFooterElement,
    GridHeaderFooterElements,
    GridLeft,
    GridOrderBy,
    GridSearchQueries,
    GridValidation,
)
from .search import EddieSearch, SearchField, T_Limit
from .styles import EddieFormStyle, EddieFormStyleFactory, EddieGridStyle

T_Table = t.TypeVar("T_Table", bound=BaseTable)
T_ColumnRow = t.TypeVar("T_ColumnRow", bound=BaseTable)
ArchiveMode = t.Literal["enabled", "readonly", "disabled"]


def after_change_applog(action: str, row: Row) -> None:
    """Send a structured applog event after a row change."""
    table = str(getattr(row, "_table", "")).removesuffix("_ed")
    me = auth.get_user() or {}

    backend.applog.try_fire(
        {
            "kind": "event",
            "action": f"{action}-{table}",
            "details": {
                "table": table,
                "action": action,
                "id": getattr(row, "id", None),
                "gid": getattr(row, "gid", None),
                "sync_gid": row.get("sync_gid", None) if hasattr(row, "get") else None,
                "admin_gid": me.get("gid"),
                "admin_email": me.get("email"),
            },
            "user_gid": me.get("gid"),
            "related": getattr(row, "gid", None),
        },
    )


def prepare_effdt_form_insert(form: Form) -> None:
    """Redirect an effective-dated form insert to the matching `_ed` table."""
    if not form.table._rname.endswith("_model"):
        # nothing to do
        return

    if table_ed := model_to_ed(form.table):
        # make Form insert into _ed instead:
        form.table = table_ed

        if "last_saved_by" in table_ed.fields and "last_saved_by" not in form.vars:
            user = auth.get_user()
            if user and getattr(user, "email", None):
                form.vars["last_saved_by"] = user.email


class GridTranslator:
    """Translate the built-in grid strings used by this wrapper."""

    TRANSLATIONS = {
        "Displaying rows %s thru %s of %s": "Laat rijen %s tot %s van de %s zien",
        "No rows to display": "Niets gevonden",
        "Search": "Zoeken",
        "Edit": "Bewerken",
        "Delete": "Verwijderen",
        "New": "Nieuw",
        "Submit": "Opslaan",
    }

    def __call__(self, string: str) -> str:
        """Translate a grid string, falling back to the original text."""
        return self.TRANSLATIONS.get(string, string)


type HookCallable[T] = t.Callable[[Row], None] | t.Callable[[T], None]


class SmartGrid[T: TableWithGid](Grid):
    """Grid wrapper that adds Eddie-specific search, archive, and action logic."""

    # todo: can use a clean-up but if we base it on the forked Grid then it should work for now

    db: TypeDAL

    def __init__(
        self,
        table: type[T],
        path: str,
        query: Query | bool | None = None,
        archive_query: Query | bool | None = None,
        widgets: AnyDict | None = None,
        # functions to make it easier to define callbacks that don't affect other places
        # (like `Model.after_insert()` would)
        after_insert: t.Iterable[HookCallable[T]] = (),
        after_update: t.Iterable[HookCallable[T]] = (),
        after_delete: t.Iterable[HookCallable[T]] = (),
        archive: ArchiveMode | bool = "enabled",  # archive functionality (for effdt tables)
        buttons_left: bool = True,  # like web2py supported as `buttons_placement`, default to True for Mike :)
        with_applog: bool = True,
        search_filters: t.Iterable[Field | SearchField] = (),
        limit: T_Limit | None = None,
        extra_form_html: ExtraFormHtml | None = None,
        # p4w defaults:
        search_queries: GridSearchQueries = None,
        orderby: GridOrderBy = None,
        columns: GridColumns = None,
        field_id: Field | TypedField[t.Any] | None = None,
        show_id: bool = False,
        left: GridLeft = None,
        headings: t.Sequence[str] | None = None,
        create: bool | str = True,
        details: bool = False,
        editable: bool | str = True,
        deletable: bool | str = True,
        validation: GridValidation = None,
        pre_action_buttons: GridButtons[T] = None,
        post_action_buttons: GridButtons[T] = None,
        auto_process: bool = True,
        include_action_button_text: bool = True,
        header_elements: GridHeaderFooterElements = None,
        footer_elements: GridHeaderFooterElements = None,
        groupby: GridGroupBy = None,
        json_import: JsonImportConfig | None = None,
    ) -> None:
        """Initialize grid state, callbacks, filters, and request-specific wiring."""
        self.callbacks = {
            "insert": list(after_insert) + ([functools.partial(after_change_applog, "insert")] if with_applog else []),
            "update": list(after_update) + ([functools.partial(after_change_applog, "update")] if with_applog else []),
            "delete": list(after_delete) + ([functools.partial(after_change_applog, "delete")] if with_applog else []),
        }

        self.is_effdt = str(table._rname).endswith("_model") and getattr(table, "effdt", None) is not None

        archive = self.normalize_archive_mode(archive)

        self.archive = archive != "disabled" and self.is_effdt
        self.archive_restorable = archive == "enabled"

        self.buttons_left = buttons_left
        self.extra_form_html = self._normalize_extra_form_html(extra_form_html)

        # create a deepcopy so we can modify it (locally):
        default_style_class = class_deepcopy(EddieGridStyle)
        grid_class_style = default_style_class()
        formstyle = deepcopy(EddieFormStyle)

        search = EddieSearch(
            table,
            t.cast(Query, query or table.id > 0),
            limit=limit,
            formstyle=formstyle,
            search_filters=search_filters,
        )

        # overwrite with changes from search form:
        query = search.query
        self.query = query
        self.archive_query = archive_query

        # add unique class:
        if search.grid_id not in grid_class_style.classes["grid-wrapper"]:
            grid_class_style.classes["grid-wrapper"] += f" {search.grid_id}"

        orderby = orderby or self._setup_orderby(search, table)

        field_gid = self._setup_gid_represent(path, table)
        field_id = t.cast(Field, field_id or field_gid)

        self._setup_widgets(widgets, formstyle)

        self.table = table
        self.json_import_config = json_import
        self.json_import: JsonImport | None = None
        super().__init__(
            path=path,
            query=query,
            search_form=search.search_form,
            search_queries=search_queries,
            columns=list(columns or ()),
            field_id=field_id,
            show_id=show_id,
            orderby=orderby,
            left=left,
            headings=headings,
            create=create,
            details=details,
            editable=editable,
            deletable=deletable,
            validation=validation,
            pre_action_buttons=pre_action_buttons,
            post_action_buttons=post_action_buttons,
            auto_process=False,
            rows_per_page=search.limit,
            include_action_button_text=include_action_button_text,
            search_button_text=None,
            formstyle=formstyle,
            grid_class_style=grid_class_style,
            T=GridTranslator(),
            groupby=groupby,
        )

        # note: some functions like .render() run AFTER the on_success -> auth may not be available.
        # -> store the current user in the grid instance (which is still request-local):
        self.auth_user = auth.get_user()

        self.parts = self.path.split("/")

        header_elements, footer_elements = self.init_grid_buttons(
            header_elements=header_elements, footer_elements=footer_elements
        )

        param = {
            "header_elements": header_elements,
            "footer_elements": footer_elements,
            "new_submit_value": self.T("Submit"),
            "edit_submit_value": self.T("Submit"),
        }

        for key, value in param.items():
            if value is not None:
                self.param[key] = value

        if auto_process:
            self.process()

    def init_grid_buttons(
        self,
        header_elements: GridHeaderFooterElements = None,
        footer_elements: GridHeaderFooterElements = None,
    ) -> tuple[list[GridHeaderFooterElement], list[GridHeaderFooterElement]]:
        """Initializes grid header and footer buttons.

        Adds relevant elements and binding parameters for all applicable buttons.
        """
        header_elements: list[GridHeaderFooterElement] = list(header_elements or [])
        footer_elements: list[GridHeaderFooterElement] = list(footer_elements or [])
        if self.json_import_config:
            header_elements.append(
                GridHeaderButton(
                    text="JSON import",
                    url=URL(self.endpoint, "import"),
                    icon="fa-file-import",
                ),
            )
        if self.archive:
            header_elements.append(self.archive_button())

        for elt in header_elements + footer_elements:
            if not isinstance(elt, GridActionButton):
                continue

            elt.bind_param(self.param)
        return header_elements, footer_elements

    @classmethod
    def normalize_archive_mode(cls, archive: ArchiveMode | bool) -> ArchiveMode:
        """Normalizes the archive mode input into a standardized ArchiveMode string."""
        archive_modes = t.get_args(ArchiveMode)
        archive_mode_options = ", ".join(archive_modes)

        if isinstance(archive, bool):
            warnings.warn(
                f"Boolean archive values are deprecated; use one of: {archive_mode_options}.",
                DeprecationWarning,
                stacklevel=2,
            )
            return "enabled" if archive else "disabled"
        elif archive not in archive_modes:
            raise ValueError(f"Unknown archive mode {archive}; expected one of: {archive_mode_options}.")
        else:
            return archive

    def _setup_widgets(self, widgets: AnyDict | None, formstyle: EddieFormStyleFactory) -> None:
        if not widgets:
            return

        for widget in widgets.values():
            if hasattr(widget, "set_form_style"):
                widget.set_form_style(formstyle)

        formstyle.widgets.update(widgets)

    def _setup_orderby(self, search: EddieSearch, table: type[T]) -> GridOrderBy:
        if search.orderby:
            return search.orderby
        elif getattr(table, "sync_gid", None):
            assert table.sync_gid
            return [~table.sync_gid]
        elif getattr(table, "effdt", None):
            assert table.effdt and table.id
            return [~table.effdt, ~table.id]
        else:
            return [~table.id]

    def _setup_gid_represent(self, path: str, table: type[TableWithGid]) -> Field | None:
        if getattr(table, "gid", None) and table.gid and table.gid.readable:
            field_id = table.gid
            assert field_id

            # replace gid in grid with clipboard icon if 'select'
            # default to just showing the gid (e.g. 'select/archive' page)
            field_id.represent = short_uuid if path.strip("/") == "select" else lambda val, _=None: str(val)
            return t.cast(Field, field_id)

        return None

    @classmethod
    def _normalize_extra_form_html(
        cls,
        value: ExtraFormHtml | None,
    ) -> dict[int, ExtraFormHtmlItem | list[ExtraFormHtmlItem]]:
        if value is None:
            return {}
        elif isinstance(value, dict):
            return value
        elif isinstance(value, list):
            return dict(enumerate(value))
        else:
            return {AFTER_LAST_FIELD: value}

    @staticmethod
    def count_form_controls(form: Form) -> int:
        """Count the children py4web appends below the last field: delete, submit, formname, formkey."""
        return 1 + bool(form.deletable) + bool(form.form_name) + bool(form.formkey)

    def render_form(self, form: Form) -> DIV:
        """Render a form and inject any extra helper elements around it."""
        form_html = form.helper()["form"]

        if database_error := form.errors.get("database"):
            form_html.insert(0, DIV(database_error, _class="alert alert-danger"))

        if self.extra_form_html:
            for idx, elements in self.extra_form_html.items():
                elements = [elements] if not isinstance(elements, list) else elements
                elements = [elt(form) if callable(elt) else elt for elt in elements]

                if idx == AFTER_LAST_FIELD:
                    idx = -self.count_form_controls(form)

                if idx < 0:
                    # temporarily remove last elements so we can put them back at the end afterwards:
                    last_elements = reversed([form_html.children.pop() for _ in range(abs(idx))])

                    form_html.children.extend(elements)
                    form_html.children.extend(last_elements)
                else:
                    # x = [1,2,3]
                    # x[0:0] = [4,5,6] -> [4, 5, 6, 1, 2, 3]
                    form_html.children[idx:idx] = elements

        return DIV(
            # a record that does not exist yet has no earlier versions to browse
            self.archive_button() if self.archive and form.record else "",
            form_html,
        )

    def render(self) -> HTMLElement | FormWithParam:
        """Render the grid or form, with archive-specific handling when needed."""
        if self.buttons_left:
            # just before rendering so we know all Columns are ready
            self.move_buttons_column_left()

        if self.action == "archive":
            # custom rendering
            return self.render_archive()
        elif self.action == "import" and self.json_import:
            return self.json_import.render()
        else:
            table_or_form = super().render()

        if table_or_form is None:
            raise HTTP(400, f"Unexpected action '{self.action}'")

        # `extra_form_html` also has to reach the create form, which has no record; before that
        # was added here, anything passed to it was silently dropped on `new`
        if isinstance(table_or_form, Form) and (table_or_form.record or self.extra_form_html):
            return self.render_form(table_or_form)

        return table_or_form

    def render_archive(self) -> HTMLElement | FormWithParam:
        """Render the archive view for all versions of the current record."""
        table = self.table_ed
        assert table and table.effdt

        archive_scope = self.archive_query
        if archive_scope is None:
            archive_scope = table.gid.belongs(self.db(self.query)._select(self.table.gid))

        if self.parts[-1] in ("archive", "select"):
            archive_endpoint = request.fullpath.removesuffix("/select")
            grid = SmartGrid(
                table,
                path="select/archive",
                query=archive_scope,
                create=False,
                editable=False,
                deletable=False,
                buttons_left=True,
                orderby=[~table.effdt, ~table.id],
                pre_action_buttons=(
                    [
                        lambda row: GridActionButton(
                            "Versie Terugzetten",
                            URL(archive_endpoint, "restore", row.id),
                            additional_classes=[BUTTON_CLASS, "grid-button"],
                        )
                    ]
                    if self.archive_restorable
                    else []
                )
                + [
                    lambda row: GridActionButton(
                        "Archief voor deze rij",
                        URL(archive_endpoint, row.gid),
                        additional_classes=[BUTTON_CLASS, "grid-button"],
                    ),
                ],
            )
            grid.endpoint = archive_endpoint
            return grid.render()
        elif self.parts[-2] == "restore":
            # .../restore/<id>
            row_id = self.parts[-1]
            if not self.archive_restorable:
                raise HTTP(403, "You do not have access to restore an archived version.")

            if not self.db(archive_scope & (table.id == row_id)).count():
                raise HTTP(403, "Access Denied")

            user = self.auth_user
            assert user, "can't use grid without logging in"

            data = ed_restore_by_id(table, row_id, last_saved_by=user.email)

            return redirect(
                URL(
                    self.endpoint,
                    "edit",
                    data["gid"],
                )
                if data
                else URL(
                    self.endpoint,
                ),
            )
        else:
            # for specific gid:
            # note: gid has been converted to 'id' at this point:
            latest_id = self.parts[-1]
            if self.db(archive_scope & (table.id == latest_id)).count() == 0:
                raise HTTP(401, "Access Denied")

            return build_archive_table(
                table_ed=table,
                latest_id=latest_id,
                class_style=self.param.grid_class_style,
                action_buttons=(
                    [
                        lambda row: GridActionButton(
                            "Versie Terugzetten",
                            URL(request.path, "restore", row.id),
                            additional_classes=[BUTTON_CLASS, "grid-button"],
                        )
                    ]
                    if self.archive_restorable
                    else []
                ),
            )

    def archive_button(self, *classes: str) -> GridHeaderButton | None:
        """Build the archive navigation button for the current request path."""
        if "/edit/" in request.path:
            url = request.path.replace("/edit/", "/archive/")
        elif "/details/" in request.path:
            url = request.path.replace("/details/", "/archive/")
        elif "/select" in request.path:
            url = request.path.replace("/select", "/archive")
        else:
            return None

        return GridHeaderButton(
            "Archief",
            URL(url, vars=dict(request.query)),
            "fa-archive",
            override_classes=" ".join(classes),
        )

    # todo: we had a custom _make_table_pager; do we still need that?

    def process_callbacks(self, row: T | None, action: str) -> AnyDict:
        """Run post-action callbacks and return flash data for the result."""
        if not row:
            return {}

        flash = {
            "status": "success",
            "message": action,
        }

        for callback in self.callbacks[action]:
            try:
                callback(row)
            except Exception as e:
                traceback.print_exception(e)
                flash = {
                    "status": "warning",
                    "message": str(e),
                }

        return flash

    def _accepted_form_callbacks(self, form: Form) -> AnyDict:
        """Run callbacks for an accepted edit or insertion."""
        assert self.table, "Grid used without table"
        if "edit" in self.parts and "gid" in form.vars:
            row = self.table(gid=form.vars["gid"])
            return self.process_callbacks(row, "update")
        elif "new" in self.parts and "id" in form.vars:
            row = self.table(id=form.vars["id"])
            return self.process_callbacks(row, "insert")
        else:
            return {"message": "Gelukt!", "status": "success"}

    def post_process(self, old_row: T | None = None) -> None:
        """Apply callback side effects and flash messages after processing."""
        assert self.table, "Grid used without table"

        self.referrer = ""

        to_flash = {}

        if "delete" in self.parts:
            row_id = self.parts[-1]
            try:
                row = self.table_ed(int(row_id))
            except KeyError:
                # this will probably not work in an after delete but we can still try:
                row = self.table(int(row_id))

            to_flash = self.process_callbacks(t.cast(T | None, row or old_row), "delete")

        elif request.method == "POST" and (form := self.form):
            if form.accepted:
                to_flash = self._accepted_form_callbacks(form)
            elif form.errors:
                message = (
                    " ".join(str(error) for error in form.errors.values())
                    if isinstance(form.errors, Mapping)
                    else str(form.errors)
                )

                to_flash = {"message": message, "status": "danger"}

        if to_flash:
            auth.send_flash(**to_flash)

    def gid_to_row(self, gid: str) -> T | None:
        """Resolve a gid path segment to the backing row id."""
        if not is_uuid(gid):
            return None

        table = self.table
        assert table, "grid used without table?"

        if self.is_effdt:
            table_ed = self.table_ed
            row = latest_ed(self.db, table_ed, table_ed.gid == gid)
            return t.cast(T | None, row)

        return table(gid=gid)

    def _resolve_request_row(self) -> T | None:
        """Resolve the path's record and translate a GID to the grid's integer ID."""
        table = self.table
        assert table, "grid used without table?"
        parts = self.parts
        if len(parts) <= 1:
            return None
        if row := self.gid_to_row(parts[1]):
            parts[1] = str(row.id)
            self.path = "/".join(parts)
            self.record_id = row.id
            return row
        else:
            return table(parts[1])

    def _check_record_scope(self, row: T | None) -> None:
        """Authorize the resolved record before any edit, detail or delete action."""
        table = self.table
        assert table, "grid used without table?"
        if not row:
            raise HTTP(403, "Access Denied")

        record_query = table.gid == row.gid if hasattr(table, "gid") else table.id == row.id
        if not self.db(self.query & record_query).count():
            raise HTTP(403, "Access Denied")

    def process(self) -> None:
        """Dispatch the current request path to the correct grid action."""
        table = self.table
        assert table, "grid used without table?"
        parts = self.parts
        action = parts[0] if parts else "select"
        self.action = action

        if action == "import" and self.json_import_config:
            user = self.auth_user
            actor = str(getattr(user, "email", None) or "admin")
            self.json_import = JsonImport(
                self.db,
                table=self.table,
                config=self.json_import_config,
                endpoint=self.endpoint,
                actor=actor,
                query=self.query,
                after_insert=self.callbacks["insert"],
                after_update=self.callbacks["update"],
                after_delete=self.callbacks["delete"],
            )
            return self.json_import.process(is_template=len(parts) > 1 and parts[1] == "template")

        row = self._resolve_request_row()

        if action in ("edit", "details", "delete"):
            self._check_record_scope(row)

        if self.is_effdt:
            if action == "new" and request.method == "POST":
                return self.effdt_new()
            elif action == "edit" and request.method == "POST":
                # edit is handled by `update_record`
                pass
            elif action == "delete" and row:
                return self.effdt_delete(row)
            elif action == "archive":
                return self.process_archive(old_row=row)

        return self.process_custom(old_row=row)

    def process_archive(self, old_row: T | None = None) -> None:
        """Run base grid setup for archive routes without record lookup on the model table."""
        original_path = self.path
        original_action = self.action
        original_record_id = self.record_id

        self.path = "select"
        self.action = "select"
        self.record_id = None

        try:
            self.process_custom(old_row=old_row)
        finally:
            self.path = original_path
            self.action = original_action
            self.record_id = original_record_id

    def process_custom(self, old_row: T | None = None) -> None:
        """Run the base grid processor and then apply custom post-processing."""
        if self.param.columns:
            # strip out None columns
            self.param.columns = [fld for fld in self.param.columns if fld is not None]
        try:
            super().process()

            if self.rows and isinstance(self.table, TableMeta):
                # turn Rows[Row] into TypedRows[T]
                self.rows = TypedRows(rows=self.rows, model=self.table)

        except HTTP as http:
            # redirect, errors etc.
            raise http
        finally:
            self.post_process(old_row=old_row)

    def effdt_new(self) -> None:
        """Create a new effective-dated record using the custom form setup."""
        if not self.is_creatable():
            raise HTTP(403, "Kan dit element niet aanmaken.")

        custom_validation = self.param.validation

        def validate_form(form: Form) -> None:
            """Prepare the effective-dated insert before running model-specific validation."""
            prepare_effdt_form_insert(form)
            if custom_validation:
                custom_validation(form)

        self.param.validation = validate_form
        return self.process_custom()

    def effdt_delete(self, record: T) -> t.Any:
        """Delete an effective-dated record by closing it out and redirecting."""
        if not self.is_deletable(t.cast(Row, record)):
            raise HTTP(403, "Kan dit element niet verwijderen.")
        user = self.auth_user
        assert user, "can't use grid without user"

        update_effectivedated(
            self.db,
            self.table_ed,
            self.table_ed.gid == record.gid,
            last_saved_by=user.email,
            delete=True,
        )

        url = parse_referrer(request)
        if url and url.query:
            self.endpoint += f"?{url.query}"

        self.post_process(old_row=record)
        return redirect(self.endpoint)

    @property
    def table_ed(self) -> type[EffdtTable]:
        """Return the `_ed` table matching the current model table."""
        assert self.table, "Grid used without table"

        table_model = str(self.table._rname)
        table_ed: str = table_model.removesuffix("_model") + "_ed"

        cls_ed = self.db.find_model(table_ed)

        if not cls_ed:
            raise KeyError(f"Could not find editable table for {self.table} (Model {table_ed} not found)")

        return t.cast(type[EffdtTable], cls_ed)

    def move_buttons_column_left(self) -> None:
        """Move the action buttons column to the first visible position."""
        columns = self.param.columns
        columns.insert(0, columns.pop())  # pop last into first

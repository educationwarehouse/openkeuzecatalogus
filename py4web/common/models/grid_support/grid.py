"""EddieGrid runtime orchestration."""

import functools
import traceback
import typing as t
from copy import deepcopy

from py4web.utils.form import Form
from py4web.utils.grid import parse_referrer
from typedal import TypeDAL, TypedRows, TypedTable
from typedal.tables import TableMeta
from typedal.types import Field, Query, Row
from yatl import TAGGER as HTMLElement
from yatl.helpers import DIV, SPAN, A, I

from common.models import auth, backend
from py4web import HTTP, URL, redirect, request
from shared_code.data_model import update_effectivedated
from shared_code.data_model.mixins.effdt import EffdtTable, ed_restore_by_id, latest_ed
from shared_code.data_model.representers.uuid import short_uuid
from shared_code.data_model.tables import BaseTable
from shared_code.data_model.validators.is_uuid import is_uuid
from shared_code.util.class_utils import class_deepcopy
from shared_code.util.exceptions import throw

from .actions import BUTTON_CLASS, GridActionButton
from .archive import build_archive_table
from .py4web_grid import (
    ExtraFormHtml,
    ExtraFormHtmlItem,
    FormWithParam,
    Grid,
    GridButtons,
    GridColumns,
    GridGroupBy,
    GridHeaderFooterElements,
    GridLeft,
    GridOrderBy,
    GridSearchQueries,
    GridValidation,
)
from .search import EddieSearch, SearchField, T_Limit
from .styles import EddieFormStyle, EddieFormStyleFactory, EddieGridStyle, prepare_effdt_form_insert

T_Table = t.TypeVar("T_Table", bound=BaseTable)
T_ColumnRow = t.TypeVar("T_ColumnRow", bound=BaseTable)


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


class SmartGrid[T: TypedTable](Grid):
    """Grid wrapper that adds Eddie-specific search, archive, and action logic."""

    # todo: can use a clean-up but if we base it on the forked Grid then it should work for now

    db: TypeDAL

    def __init__(
        self,
        table: type[T],
        path: str,
        query: Query | bool | None = None,
        *,
        widgets: dict[str, t.Any] | None = None,
        # functions to make it easier to define callbacks that don't affect other places
        # (like `Model.after_insert()` would)
        after_insert: t.Iterable[t.Callable[[Row], None]] = (),
        after_update: t.Iterable[t.Callable[[Row], None]] = (),
        after_delete: t.Iterable[t.Callable[[Row], None]] = (),
        archive: bool = True,  # archive functionality (for effdt tables)
        buttons_left: bool = True,  # like web2py supported as `buttons_placement`, default to True for Mike :)
        with_applog: bool = True,
        search_filters: t.Iterable[Field | SearchField] = (),
        limit: T_Limit | None = None,
        extra_form_html: ExtraFormHtml | None = None,
        # p4w defaults:
        search_queries: GridSearchQueries = None,
        orderby: GridOrderBy = None,
        columns: GridColumns = None,
        field_id: Field | None = None,
        show_id: bool = False,
        left: GridLeft = None,
        headings: t.Sequence[str] | None = None,
        create: bool | str = True,
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
    ) -> None:
        """Initialize grid state, callbacks, filters, and request-specific wiring."""
        self.callbacks = {
            "insert": list(after_insert) + ([functools.partial(after_change_applog, "insert")] if with_applog else []),
            "update": list(after_update) + ([functools.partial(after_change_applog, "update")] if with_applog else []),
            "delete": list(after_delete) + ([functools.partial(after_change_applog, "delete")] if with_applog else []),
        }

        self.is_effdt = str(table._rname).endswith("_model") and getattr(table, "effdt", None) is not None
        self.archive = archive and self.is_effdt
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

        # add unique class:
        if search.grid_id not in grid_class_style.classes["grid-wrapper"]:
            grid_class_style.classes["grid-wrapper"] += f" {search.grid_id}"

        orderby = orderby or self._setup_orderby(search, table)

        field_gid = self._setup_gid_represent(path, table)
        field_id = field_id or field_gid

        self._setup_widgets(widgets, formstyle)

        self.table = table
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
            details=False,
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

        if query and self.action in ("edit", "details", "delete"):
            parts = path.split("/")  # edit / gid / ...
            gid = parts[1]

            # check if current gid matches query -> allowed to see:
            # if not table.where(query).where(table.gid == parts[1]).exists():
            if hasattr(table, "gid") and is_uuid(gid) and self.db(query & (table.gid == gid)).count() == 0:
                raise HTTP(401, "Access Denied")

        header_elements = list(header_elements or [])
        footer_elements = list(footer_elements or [])
        if self.archive:
            header_elements.append(lambda: self.archive_button("ms-3"))

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

    def _setup_widgets(self, widgets: dict[str, t.Any] | None, formstyle: EddieFormStyleFactory) -> None:
        if not widgets:
            return

        for widget in widgets.values():
            if hasattr(widget, "set_form_style"):
                widget.set_form_style(formstyle)

        formstyle.widgets.update(widgets)

    def _setup_orderby(self, search: EddieSearch, table: type[TypedTable]) -> GridOrderBy:
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

    def _setup_gid_represent(self, path: str, table: type[TypedTable]) -> Field | None:
        if getattr(table, "gid", None) and table.gid and table.gid.readable:
            field_id = table.gid
            assert field_id

            # replace gid in grid with clipboard icon if 'select'
            # default to just showing the gid (e.g. 'select/archive' page)
            field_id.represent = short_uuid if path.strip("/") == "select" else lambda val, _=None: str(val)
            return field_id
        return None

    @classmethod
    def _normalize_extra_form_html(
        cls,
        value: ExtraFormHtml | None,
    ) -> dict[int, ExtraFormHtmlItem | list[ExtraFormHtmlItem]]:
        if value is None:
            return {}

        if isinstance(value, dict):
            return value  # type: ignore

        if isinstance(value, list):
            return dict(enumerate(value))  # type: ignore

        return {-4: value}

    def render_form(self, form: Form) -> DIV:
        """Render a form and inject any extra helper elements around it."""
        form_html = form.helper()["form"]

        if self.extra_form_html:
            for idx, elements in self.extra_form_html.items():
                elements = [elements] if not isinstance(elements, list) else elements
                elements = [elt(form) if callable(elt) else elt for elt in elements]  # type: ignore

                if idx < 0:
                    # temporarily remove last elements so we can put them back at the end afterwards:
                    last_elements = reversed([form_html.children.pop() for _ in range(abs(idx))])
                    # check to delete, submit button, form name, form key

                    form_html.children.extend(elements)
                    form_html.children.extend(last_elements)
                else:
                    # x = [1,2,3]
                    # x[0:0] = [4,5,6] -> [4, 5, 6, 1, 2, 3]
                    form_html.children[idx:idx] = elements

        return DIV(
            self.archive_button() if self.archive else "",
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
        else:
            table_or_form = super().render()

        if table_or_form is None:
            raise HTTP(400, f"Unexpected action '{self.action}'")

        if isinstance(table_or_form, Form) and table_or_form.record:
            return self.render_form(table_or_form)

        return table_or_form

    def render_archive(self) -> HTMLElement | FormWithParam:
        """Render the archive view for all versions of the current record."""
        table = self.table_ed
        assert table and table.effdt

        if self.parts[-1] == "archive":
            grid = SmartGrid(
                table,
                path="select/archive",
                create=False,
                editable=False,
                deletable=False,
                buttons_left=True,
                orderby=[~table.effdt, ~table.id],
                pre_action_buttons=[
                    lambda row: GridActionButton(
                        "Versie Terugzetten",
                        URL(request.path, "restore", row.id),
                        additional_classes=[BUTTON_CLASS, "grid-button"],
                    ),
                    lambda row: GridActionButton(
                        "Archief voor deze rij",
                        URL(request.path, row.gid),
                        additional_classes=[BUTTON_CLASS, "grid-button"],
                    ),
                ],
            )
            return grid.render()
        elif self.parts[-2] == "restore":
            # .../restore/<id>
            row_id = self.parts[-1]

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
            return build_archive_table(
                table_ed=table,
                # note: gid has been converted to 'id' at this point:
                latest_id=self.parts[-1],
                class_style=self.param.grid_class_style,
                action_buttons=[
                    lambda row: GridActionButton(
                        "Versie Terugzetten",
                        URL(request.path, "restore", row.id),
                        additional_classes=[BUTTON_CLASS, "grid-button"],
                    )
                ],
            )

    def archive_button(self, *classes: str) -> HTMLElement:
        """Build the archive navigation button for the current request path."""
        if "/edit/" in request.path:
            url = request.path.replace("/edit/", "/archive/")
        elif "/details/" in request.path:
            url = request.path.replace("/details/", "/archive/")
        elif "/select" in request.path:
            url = request.path.replace("/select", "/archive")
        else:
            return SPAN()

        return A(
            SPAN(
                I(_class="fas fa-archive px-1"),
                "Archief",
                **self.param.grid_class_style.get("grid-header-button"),
            ),
            _class="grid-new-button " + " ".join(classes),
            _href=url,
        )

    # todo: we had a custom _make_table_pager; do we still need that?

    def process_callbacks(self, row: Row | None, action: str) -> dict[str, t.Any]:
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

    def post_process(self, old_row: Row | None = None) -> None:
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

            to_flash = self.process_callbacks(t.cast(Row, row or old_row), "delete")

        elif request.method == "POST" and (form := self.form):
            if form.accepted:
                if "edit" in self.parts and "gid" in form.vars:
                    row = t.cast(Row | None, self.table(gid=form.vars["gid"]))
                    to_flash = self.process_callbacks(row, "update")
                elif "new" in self.parts and "id" in form.vars:
                    row = t.cast(Row | None, self.table(id=form.vars["id"]))
                    to_flash = self.process_callbacks(row, "insert")
                else:
                    to_flash = {"message": "Gelukt!", "status": "success"}
            elif form.errors:
                to_flash = {"message": str(form.errors), "status": "danger"}

        if to_flash:
            auth.send_flash(**to_flash)

    def gid_to_row(self, gid: str) -> TypedTable | None:
        """Resolve a gid path segment to the backing row id."""
        if not is_uuid(gid):
            return None

        table = self.table
        assert table, "grid used without table?"

        if self.is_effdt:
            table_ed = self.table_ed
            return latest_ed(self.db, table_ed, table_ed.gid == gid)

        return table(gid=gid)

    def process(self) -> None:
        """Dispatch the current request path to the correct grid action."""
        table = self.table
        assert table, "grid used without table?"
        row = None

        # Grid loves integer ids so let's convert it
        if (parts := self.parts) and len(parts) > 1:
            if row := self.gid_to_row(parts[1]):
                parts[1] = str(row.id)
                self.path = "/".join(parts)
                self.record_id = row.id
            else:
                row = table(parts[1])

        action = parts[0] if parts else "select"
        self.action = action
        if self.is_effdt:
            if action == "new" and request.method == "POST":
                return self.effdt_new()
            elif action == "edit" and request.method == "POST":
                # edit is handled by `update_record`
                pass
            elif action == "delete" and row:
                return self.effdt_delete(t.cast(Row, row))
            elif action == "archive":
                return self.process_archive(t.cast(Row | None, row))

        return self.process_custom(t.cast(Row | None, row))

    def process_archive(self, old_row: Row | None = None) -> None:
        """Run base grid setup for archive routes without record lookup on the model table."""
        original_path = self.path
        original_action = self.action
        original_record_id = self.record_id

        self.path = "select"
        self.action = "select"
        self.record_id = None

        try:
            self.process_custom(old_row)
        finally:
            self.path = original_path
            self.action = original_action
            self.record_id = original_record_id

    def process_custom(self, old_row: Row | None = None) -> None:
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
            self.post_process(old_row)

    def effdt_new(self) -> None:
        """Create a new effective-dated record using the custom form setup."""
        if not self.is_creatable():
            raise HTTP(403, "Kan dit element niet aanmaken.")

        self.param.validation = prepare_effdt_form_insert
        return self.process_custom()

    def effdt_delete(self, record: Row) -> t.Any:
        """Delete an effective-dated record by closing it out and redirecting."""
        if not self.is_deletable(record):
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

        self.post_process(record)
        return redirect(self.endpoint)

    @property
    def table_ed(self) -> type[EffdtTable]:
        """Return the `_ed` table matching the current model table."""
        assert self.table, "Grid used without table"

        table_model = str(self.table._rname)
        table_ed: str = table_model.removesuffix("_model") + "_ed"
        return self.db.find_model(table_ed) or throw(
            KeyError(f"Could not find editable table for {self.table} (Model {table_ed} not found)"),
        )

    def move_buttons_column_left(self) -> None:
        """Move the action buttons column to the first visible position."""
        columns = self.param.columns
        columns.insert(0, columns.pop())  # pop last into first

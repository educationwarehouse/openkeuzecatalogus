"""This is a fork of py4web's grid before their '33537c01 grid experimental refactor (#972)'."""

import base64
import contextlib
import datetime as dt
import typing as t

from py4web.utils.form import FormStyleFactory
from py4web.utils.grid import (
    Column,
    Expression,
    FieldVirtual,
    Form,
    FormStyleDefault,
    GridClassStyle,
    Param,
    copy,
    join_classes,
    safe_int,
    safely,
    title,
)
from py4web.utils.grid import parse_referrer as parse_referer
from pydal.objects import Field as PydalField
from typedal import TypeDAL
from typedal.types import Field as TypedalField
from typedal.types import GroupBy, OrderBy, Query, Row, Rows
from yatl import CAT, DIV, FORM, INPUT, OPTION, SELECT, SPAN, TABLE, TBODY, TD, TH, THEAD, TR, XML, A, I
from yatl import TAGGER as HTMLElement

from py4web import HTTP, URL, redirect, request

from .actions import GridActionButton

Field = TypedalField | PydalField


def clean_sc[T](**kwargs: T) -> dict[str, T]:
    """Return a clean dict with `_class` and `_style` only when set."""
    return {key: value for key, value in kwargs.items() if value}


class AttributesPlugin:
    """Provide default HTML attributes for grid-generated elements."""

    def __init__(self, target_element: HTMLElement | None = None) -> None:
        """Initialize the plugin with an optional target element."""
        self.target_element = target_element
        self.default_attrs = {}

    def form(self, url: str) -> dict[str, t.Any]:
        """Return default form attributes for a grid form."""
        attrs = copy.copy(self.default_attrs)
        return attrs

    def link(self, url: str) -> dict[str, t.Any]:
        """Return default link attributes with the supplied target URL."""
        attrs = copy.copy(self.default_attrs)
        attrs["_href"] = url
        return attrs

    def confirm(self, message: str) -> dict[str, t.Any]:
        """Return link attributes that prompt for confirmation."""
        attrs = copy.copy(self.default_attrs)
        attrs["_onclick"] = f"if(!confirm({message!r})) return false;"
        return attrs


def join_styles(items: t.Iterable[str]) -> str:
    """Join CSS style fragments into a single string."""
    return "".join(item for item in items if item) if isinstance(items, (list, tuple)) else f" {items or ''}"


type TypedParam = t.Any
type GridSearchQueryValidator = t.Callable[[str], tuple[str, str | None]]
type GridSearchQuery = tuple[str, t.Callable[[str], Query], GridSearchQueryValidator | None]
type GridSearchQueries = t.Sequence[GridSearchQuery] | t.Literal["auto"] | None
type GridColumn = Field | Expression | FieldVirtual | Column
type GridColumns = t.Sequence[GridColumn] | None
type GridOrderBy = OrderBy | t.Sequence[OrderBy] | None
type GridGroupBy = GroupBy | t.Sequence[GroupBy] | None
type GridLeft = Expression | t.Sequence[Expression] | None
type GridValidation = t.Callable[[Form], None] | None
type GridButton = GridActionButton | HTMLElement | dict[str, t.Any] | str
type GridButtonFactory = t.Callable[[Row], GridButton | None]
type TypedGridButtonFactory[T] = t.Callable[[T], GridButton | None]

type GridButtons[T] = t.Sequence[GridButton | GridButtonFactory | TypedGridButtonFactory[T]] | None
type GridHeaderFooterElement = GridActionButton | HTMLElement | str | t.Callable[[], HTMLElement | str]
type GridHeaderFooterElements = t.Sequence[GridHeaderFooterElement] | None
type ExtraFormHtmlItem = HTMLElement | str | t.Callable[[Form], HTMLElement | str]
type ExtraFormHtml = (
    dict[int, ExtraFormHtmlItem | list[ExtraFormHtmlItem]] | ExtraFormHtmlItem | list[ExtraFormHtmlItem]
)


class FormWithParam(Form):
    """Form subclass that carries the grid parameter bag."""

    param: TypedParam


class Grid:
    """Forked py4web grid implementation with project-specific behavior."""

    param: TypedParam

    FORMATTERS_BY_TYPE = {
        "boolean": lambda value: INPUT(_type="checkbox", _checked=value, _disabled="disabled") if value else "",
        "datetime": lambda value: (
            XML(f"""<script>
            document.write(
            (new Date({value.year},{value.month - 1},{value.day},{value.hour},{value.minute},{value.second})
            ).toLocaleString())
            </script>""")
            if value and isinstance(value, dt.datetime)
            else value
            if value
            else ""
        ),
        "time": lambda value: (
            XML(f"""<script>
            document.write(
            (new Date(0, 0, 0,{value.hour},{value.minute},{value.second})).toLocaleString().split(', ')[1])
            </script>""")
            if value and isinstance(value, dt.time)
            else value
            if value
            else ""
        ),
        "date": lambda value: (
            XML(f"""<script>
            document.write(
            (new Date({value.year},{value.month - 1},{value.day})).toLocaleString().split(",")[0])
            </script>""")
            if value and isinstance(value, dt.date)
            else value
            if value
            else ""
        ),
        "list:string": lambda value: ", ".join(str(x) for x in value) if value else "",
        "list:integer": lambda value: ", ".join(x for x in value) if value else "",
        "default": lambda value: str(value) if value is not None else "",
    }

    def __init__(
        self,
        path: str,
        query: Query,
        search_form: Form | None = None,
        search_queries: GridSearchQueries = None,
        columns: GridColumns = None,
        field_id: Field | None = None,
        show_id: bool = False,
        orderby: GridOrderBy = None,
        left: GridLeft = None,
        headings: t.Sequence[str] | None = None,
        create: bool | str = True,
        details: bool | str = True,
        editable: bool | str = True,
        deletable: bool | str = True,
        validation: GridValidation = None,
        pre_action_buttons: GridButtons = None,
        post_action_buttons: GridButtons = None,
        auto_process: bool = True,
        rows_per_page: int = 15,
        include_action_button_text: bool = True,
        search_button_text: str | None = "Filter",
        formstyle: FormStyleFactory = FormStyleDefault,
        grid_class_style: GridClassStyle | type[GridClassStyle] = GridClassStyle,
        T: t.Callable[[str], str] = lambda text: text,
        groupby: GridGroupBy = None,
        header_elements: GridHeaderFooterElements = None,
        footer_elements: GridHeaderFooterElements = None,
        # deprecated
        fields: GridColumns = None,
    ) -> None:
        """Grid is a searchable/sortable/pageable grid.

        :param path: The part of the URL to be parsed by this grid
        :param query: the query used to filter the data
        :param search_form: py4web FORM to be included as the search form
        :param search_queries: future use - pass a dict of name and a search query
        :param columns: list of columns to display on the list page, if blank, glean tablename from first query
        :              and use all fields of that table
        :param field_id: the id field of the primary table for the grid - if there are multiple tables (joined)
                            then the table for this field is used as the table for edit/details/delete
        :param show_id: show the record id field on list page - default = False
        :param orderby: pydal orderby field or list of fields
        :param left: if joining other tables, specify the pydal left expression here
        :param headings: list of headings to be used for list page - if not provided use the field label
        :param create: URL to redirect to for creating records - set to False to not display the button
        :param editable: URL to redirect to for editing records - set to False to not display the button
        :param deletable: URL to redirect to for deleting records - set to False to not display the button
        :param validation: optional validation function to pass to create and edit forms
        :param pre_action_buttons: list of Column instances to include before the standard action buttons
        :param post_action_buttons: list of Column instances to include after the standard action buttons
        :param auto_process: True/False - automatically process the sql for the form - if False, user is
                              responsible for calling process().
        :param T: optional pluralize object
        """
        if path in (None, "", "index"):
            fullpath = request.fullpath.rstrip("/")
            if path == "index":
                fullpath = fullpath[:-6]
            redirect(f"{fullpath}/select" + (f"?{request.query_string}" if request.query_string else ""))

        # in case the query is a Table insteance
        if query and isinstance(query, query._db.Table):
            query = query._id != None

        assert query, "can't use grid without query"

        self.path = path
        self.db: TypeDAL = query._db
        self.T = T
        self.param = Param(
            query=query,
            columns=columns or fields,
            field_id=field_id,
            show_id=show_id,
            orderby=orderby,
            left=left,
            groupby=groupby,
            search_form=search_form,
            search_queries=search_queries,
            headings=headings or [],
            create=create,
            details=details,
            editable=editable,
            deletable=deletable,
            validation=validation,
            pre_action_buttons=pre_action_buttons,
            post_action_buttons=post_action_buttons,
            rows_per_page=rows_per_page,
            include_action_button_text=include_action_button_text,
            search_button_text=search_button_text,
            formstyle=formstyle,
            grid_class_style=grid_class_style,
            new_sidecar=None,
            new_submit_value=None,
            new_action_button_text="New",
            details_sidecar=None,
            details_submit_value=None,
            details_action_button_text="Details",
            edit_sidecar=None,
            edit_submit_value=None,
            edit_action_button_text="Edit",
            delete_action_button_text="Delete",
            header_elements=header_elements,
            footer_elements=footer_elements,
        )

        #  instance variables that will be computed
        self.action = None
        self.current_page_number = 1
        self.endpoint = request.fullpath[: -len(self.path)].rstrip("/")
        self.hidden_fields = None
        self.form = None
        self.number_of_pages = 0
        self.page_end = 0
        self.page_start = 0
        self.query_parms = safely(lambda: request.params, default={})
        self.record_id = None
        self.rows: Rows | None = None
        self.tablename = None
        self.total_number_of_rows = 0
        self.use_tablename = self.is_join()
        self.formatters: dict[str, t.Callable[[Row], dict[str, str]]] = {}
        self.formatters_by_type = copy.copy(Grid.FORMATTERS_BY_TYPE)
        self.attributes_plugin = AttributesPlugin()

        if auto_process:
            self.process()

    def is_creatable(self) -> bool:
        """Return whether the current action allows record creation."""
        if self.param.groupby:
            return False
        if callable(self.param.create):
            return self.param.create()
        return self.param.create

    def is_editable(self, row: Row | None) -> bool:
        """Return whether the current row can be edited."""
        if self.param.groupby:
            return False
        if callable(self.param.editable):
            return self.param.editable(row)
        return self.param.editable

    def is_readable(self, row: Row | None) -> bool:
        """Return whether the current row can be viewed."""
        if callable(self.param.details):
            return self.param.details(row)
        return self.param.details

    def is_deletable(self, row: Row | None) -> bool:
        """Return whether the current row can be deleted."""
        # cannot delete a record that does not exist
        if row is None:
            return False
        # cannot delete if the a record is grouped
        if self.param.groupby:
            return False
        # if deletable is callable, call it
        if callable(self.param.deletable):
            return self.param.deletable(row)
        # if deletable is boolean, check it
        return self.param.deletable

    def process(self) -> None:  # noqa C901: this is too complex
        # but forked from py4web so harder to rewrite right now (todo)
        """Resolve the request context, load rows, and prepare grid state."""
        query = None
        db = self.db
        if not self.param.search_form and self.param.search_queries:
            search_type = safe_int(request.query.get("search_type", 0), default=0)
            search_string = request.query.get("search_string")
            if search_type < len(self.param.search_queries) and search_string:
                query_lambda = self.param.search_queries[search_type][1]
                with contextlib.suppress(Exception):
                    query = query_lambda(search_string)

        if not query:
            query = self.param.query
        else:
            query &= self.param.query

        parts = self.path.split("/")
        self.action = parts[0] or "select"

        if self.param.field_id:
            self.tablename = str(self.param.field_id._table)
        else:
            self.tablename = self.get_tablenames(self.param.query)[0]
            self.param.field_id = db[self.tablename]._id

        self.record_id = safe_int(parts[1] if len(parts) > 1 else None, default=None)

        table = db[self.tablename]
        if not self.param.columns:
            # if no column specified use all fields
            self.param.columns = [field for field in table if field.readable]

        #  if any columns are Expression but not Field, get the field info from 'first' attribute
        converted_columns = []
        for col in self.param.columns:
            if isinstance(col, Expression) and not isinstance(col, Field):
                converted_columns.append(col.first)
            else:
                converted_columns.append(col)
        self.param.columns = converted_columns

        if not self.param.columns:
            self.needed_fields = self.param.columns[:]
        elif any(isinstance(col, Column) for col in self.param.columns):
            # if we use columns we have to get all fields and assume a single table
            self.needed_fields = list(db[self.tablename])
            for col in self.param.columns:
                if isinstance(col, Column):
                    for rf in col.required_fields:
                        if rf.longname not in [x.longname for x in self.needed_fields]:
                            self.needed_fields.append(rf)
        elif any(isinstance(col, FieldVirtual) for col in self.param.columns):
            # if virtual fields are specified the fields may come from a join
            needed_fields = set()
            for col in self.param.columns:
                if isinstance(col, Field):
                    needed_fields.add(col)
                elif isinstance(col, FieldVirtual):
                    for field in db[col.tablename]:
                        needed_fields.add(field)
            self.needed_fields = list(needed_fields)
        else:
            self.needed_fields = self.param.columns[:]

        # make sure all specified fields are available
        if self.param.columns:
            for col in self.param.columns:
                if not isinstance(col, (Column, FieldVirtual)) and col.longname not in (
                    x.longname for x in self.needed_fields
                ):
                    self.needed_fields.append(col)

        # except the primary key may be missing and must be fetched even if not displayed
        if not any(col.name == table._id.name for col in self.needed_fields):
            self.needed_fields.insert(0, table._id)

        self.referrer = None

        if not self.tablename:
            raise HTTP(400)

        # SECURITY: if the record does not exist or does not match query, than we are not allowed
        table = db[self.tablename]

        record: Row | None
        if self.record_id:
            record = table(self.record_id)
            if not record:
                redirect(self.endpoint)
        else:
            record = None

        #  ensure the user has access for new/details/edit/delete if chosen
        if self.action == "new" and not self.is_creatable():
            raise HTTP(
                403,
                f"You do not have access to create a record in the {self.tablename} table.",
            )
        if self.action == "details" and not self.is_readable(record):
            raise HTTP(
                403,
                f"You do not have access to read a record from the {self.tablename} table.",
            )
        if self.action == "edit" and not self.is_editable(record):
            raise HTTP(
                403,
                f"You do not have access to edit a record in the {self.tablename} table.",
            )
        if self.action == "delete" and not self.is_deletable(record):
            raise HTTP(
                403,
                f"You do not have access to delete a record in the {self.tablename} table.",
            )

        if self.action in ["new", "details", "edit"]:
            readonly = self.action == "details"

            attrs = self.attributes_plugin.form(url=request.url.split(":", 1)[1])
            self.form = FormWithParam(
                table,
                record=record,
                readonly=readonly,
                deletable=self.is_deletable(record),
                formstyle=self.param.formstyle,
                validation=self.param.validation,
                show_id=self.param.show_id,
                **attrs,
            )
            if self.action == "new" and self.param.create:
                if self.param.new_sidecar:
                    self.form.param.sidecar.append(self.param.new_sidecar)
                if self.param.new_submit_value:
                    self.form.param.submit_value = self.param.new_submit_value
            if self.action == "details" and self.is_readable(record):
                if self.param.details_sidecar:
                    self.form.param.sidecar.append(self.param.details_sidecar)
                if self.param.details_submit_value:
                    self.form.param.submit_value = self.param.details_submit_value
            if self.action == "edit" and self.is_editable(record):
                if self.param.edit_sidecar:
                    self.form.param.sidecar.append(self.param.edit_sidecar)
                if self.param.edit_submit_value:
                    self.form.param.submit_value = self.param.edit_submit_value

            # redirect to the referrer
            if self.form.accepted or (readonly and request.method == "POST"):
                referrer = request.query.get("_referrer")
                if referrer:
                    redirect(base64.b16decode(referrer.encode("utf8")).decode("utf8"))
                else:
                    redirect(self.endpoint)

        elif self.action == "delete" and self.is_deletable(record):
            db(db[self.tablename].id == self.record_id).delete()

            referrer = parse_referer(request)
            url = self.endpoint + "/select"
            if referrer and referrer.query:
                url += f"?{referrer.query}"
            redirect(url)

        elif self.action == "select":
            self.referrer = f"_referrer={base64.b16encode(request.url.encode('utf8')).decode('utf8')}"

            #  find the primary key of the primary table
            pt = db[self.tablename]
            key_is_missing = True
            for field in self.param.columns:
                if isinstance(field, Field) and field.table._tablename == pt._tablename and field.name == pt._id.name:
                    key_is_missing = False
            if key_is_missing:
                #  primary key wasn't included, add it and set show_id to False so it doesn't display
                self.param.columns.append(pt._id)
                self.param.show_id = False

            self.current_page_number = safe_int(request.query.get("page"), default=1)

            select_params = {}
            #  try getting sort order from the request
            sort_order = request.query.get("orderby", "")

            try:
                parts = sort_order.lstrip("~").split(".")
                orderby = db[parts[0]][parts[1]]
                if sort_order.startswith("~"):
                    orderby = ~orderby
                select_params["orderby"] = orderby
            except IndexError, KeyError, TypeError, AttributeError:
                select_params["orderby"] = self.param.orderby

            if self.param.left:
                select_params["left"] = self.param.left

            if self.param.groupby:
                select_params["groupby"] = self.param.groupby

            if self.param.groupby:
                #  need groupby fields in select to get proper count
                self.total_number_of_rows = len(db(query).select(*self.param.groupby, **select_params))
            elif self.param.left:
                # TODO: maybe this can be made more efficient
                self.total_number_of_rows = len(db(query).select(db[self.tablename].id, **select_params))
            else:
                self.total_number_of_rows = db(query).count()

            #  if at a high page number and then filter causes less records to be displayed, reset to page 1
            if (self.current_page_number - 1) * self.param.rows_per_page > self.total_number_of_rows:
                self.current_page_number = 1

            if self.total_number_of_rows > self.param.rows_per_page:
                self.page_start = self.param.rows_per_page * (self.current_page_number - 1)
                self.page_end = self.page_start + self.param.rows_per_page
                select_params["limitby"] = (self.page_start, self.page_end)
            else:
                self.page_start = 0
                if self.total_number_of_rows > 1:
                    self.page_start = 1
                self.page_end = self.total_number_of_rows

            # get the data
            self.rows = db(query).select(*self.needed_fields, **select_params)

            self.number_of_pages = self.total_number_of_rows // self.param.rows_per_page
            if self.total_number_of_rows % self.param.rows_per_page > 0:
                self.number_of_pages += 1

        if (
            self.param.pre_action_buttons
            or self.param.details
            or self.param.editable
            or self.param.deletable
            or self.param.post_action_buttons
        ):
            self.param.columns.append(Column("", self.make_action_buttons, td_class_style="grid-td-buttons"))

    def iter_pages(
        self,
        current_page: int,
        num_pages: int,
        left_current: int = 1,
        right_current: int = 1,
        left_edge: int = 1,
        right_edge: int = 1,
    ) -> list[int]:
        """Yield the page numbers that should appear in the pager.

        :param left_current: # of pages to add to the left of current page
        :param right_current: # of fpages to add to the right of current page
        :param left_edge: # of pages to add to the left end
        :param right_edge: # of fpages to add to the right end
        """
        left_range = set(range(1, min(2 + left_edge, num_pages + 1)))
        mid_range = set(
            range(
                max(1, current_page - left_current),
                min(current_page + right_current + 1, num_pages + 1),
            )
        )
        right_range = set(range(max(1, num_pages - right_edge), num_pages + 1))
        return sorted(left_range | mid_range | right_range)

    def _make_action_button(  # noqa C901: this is too complex
        # but forked from py4web so harder to rewrite right now (todo)
        self,
        url: str | t.Callable[[Row | None], str],
        button_text: str,
        icon: str,
        icon_size: str = "small",  # deprecated
        additional_classes: t.Any = None,
        additional_styles: t.Any = None,
        override_classes: t.Any = None,
        override_styles: t.Any = None,
        message: str | None = None,
        onclick: t.Any = None,  # deprecated
        row_id: t.Any = None,
        name: str = "grid-button",
        row: Row | None = None,
        ignore_attribute_plugin: bool = False,
        **attrs: t.Any,
    ) -> HTMLElement:
        if row_id and isinstance(url, str):
            url += f"/{row_id}"

        classes = self.param.grid_class_style.classes.get(name, "")
        styles = self.param.grid_class_style.styles.get(name, "")

        if callable(additional_classes):
            additional_classes = additional_classes(row)

        if callable(additional_styles):
            additional_styles = additional_styles(row)

        if callable(override_classes):
            override_classes = override_classes(row)

        if callable(override_styles):
            override_styles = override_styles(row)

        if override_classes:
            classes = join_classes(override_classes)
        elif additional_classes:
            classes = join_classes(classes, additional_classes)
        if override_styles:
            styles = join_styles(override_styles)
        elif additional_styles:
            styles += join_styles(additional_styles)

        url_resolved: str = url(row) if callable(url) else url  # type: ignore

        if ignore_attribute_plugin:
            attrs.update({"_href": url_resolved})
        else:
            attrs.update(self.attributes_plugin.link(url=url_resolved))

        link = A(
            I(_class=f"fa {icon}"),
            _role="button",
            _message=message,
            _title=button_text,
            **clean_sc(_class=classes, _style=styles),
            **attrs,
        )
        if self.param.include_action_button_text:
            link.append(SPAN(XML("&nbsp;"), button_text, _class="grid-action-button-text"))

        return link

    def _make_default_form(self) -> HTMLElement:
        search_type = safe_int(request.query.get("search_type", 0), default=0)
        search_string = request.query.get("search_string")
        options = [
            OPTION(items[0], _value=k, _selected=(k == search_type))
            for k, items in enumerate(self.param.search_queries)
        ]
        hidden_fields = [
            INPUT(_name=key, _value=request.query.get(key), _type="hidden")
            for key in request.query
            if key not in ("search_type", "search_string")
        ]
        attrs = self.attributes_plugin.link(url=self.endpoint)
        form = FORM(*hidden_fields, **attrs)
        sc = self.param.grid_class_style.get("grid-search-form-select")
        select = SELECT(
            *options,
            _name="search_type",
            **sc,
        )
        sc = self.param.grid_class_style.get("grid-search-form-input")
        input = INPUT(
            _type="text",
            _name="search_string",
            _value=search_string,
            **sc,
        )
        sc = self.param.grid_class_style.get("grid-search-button")
        submit = INPUT(_type="submit", _value=self.T("Search"), **sc)
        clear_script = "document.querySelector('[name=search_string]').value='';"
        sc = self.param.grid_class_style.get("grid-clear-button")
        clear = INPUT(_type="submit", _value=self.T("Clear"), _onclick=clear_script, **sc)
        div = DIV(_id="grid-search", **self.param.grid_class_style.get("grid-search"))

        sc = self.param.grid_class_style.get("grid-search-form-tr")
        tr = TR(**sc)
        sc = self.param.grid_class_style.get("grid-search-form-td")
        if len(options) > 1:
            tr.append(TD(select, **sc))
        tr.append(TD(input, **sc))
        tr.append(TD(submit, clear, **sc))
        sc = self.param.grid_class_style.get("grid-search-form-table")
        form.append(TABLE(tr, **sc))
        div.append(form)
        return div

    def _make_search_form(self) -> HTMLElement:
        div = DIV(_id="grid-search", **self.param.grid_class_style.get("grid-search"))
        div.append(self.param.search_form.custom["begin"])
        tr = TR(**self.param.grid_class_style.get("grid-search-form-tr"))
        for field in self.param.search_form.table:
            td = TD(**self.param.grid_class_style.get("grid-search-form-td"))
            if field.type == "boolean":
                sb = DIV(**self.param.grid_class_style.get("grid-search-boolean"))
                sb.append(self.param.search_form.custom["widgets"][field.name])
                sb.append(field.label)
                td.append(sb)
            else:
                td.append(self.param.search_form.custom["wrappers"][field.name])
            if (
                field.name in self.param.search_form.custom["errors"]
                and self.param.search_form.custom["errors"][field.name]
            ):
                td.append(
                    DIV(
                        self.param.search_form.custom["errors"][field.name],
                        _style="color:#ff0000",
                    )
                )
            tr.append(td)
        if self.param.search_button_text:
            tr.append(
                TD(
                    INPUT(
                        _class=self.param.grid_class_style.classes.get("grid-search-button", ""),
                        _type="submit",
                        _value=self.T(self.param.search_button_text),
                    ),
                    **self.param.grid_class_style.get("grid-search-form-td"),
                )
            )
        else:
            tr.append(
                TD(
                    self.param.search_form.custom["submit"],
                    **self.param.grid_class_style.get("grid-search-form-td"),
                )
            )
        div.append(TABLE(tr, **self.param.grid_class_style.get("grid-search-form-table")))
        for hidden_widget in self.param.search_form.custom["hidden_widgets"]:
            if hidden_widget not in ("formname", "formkey"):
                div.append(self.param.search_form.custom["hidden_widgets"][hidden_widget])

        div.append(self.param.search_form.custom["end"])

        return div

    def _make_table_header(self) -> HTMLElement:
        sort_order = request.query.get("orderby", "")

        thead = THEAD(**clean_sc(_class=self.param.grid_class_style.classes.get("grid-thead", "")))
        for index, column in enumerate(self.param.columns):
            col = None
            if isinstance(column, (Field, FieldVirtual)):
                field = column
                if field.readable and (field.type != "id" or self.param.show_id):
                    key, col = self._make_field_header(column, index, sort_order)
            elif isinstance(column, Column):
                key = column.name.lower().replace(" ", "-")
                col = column.name
                if column.orderby:
                    key, col = self._make_field_header(column, index, sort_order)
            else:
                raise RuntimeError(f"Invalid Grid Column type {type(column)}")
            if col is not None:
                classes = join_classes(
                    self.param.grid_class_style.classes.get("grid-th"),
                    f"grid-col-{key}",
                )
                style = self.param.grid_class_style.styles.get("grid-th")
                thead.append(TH(col, **clean_sc(_class=classes, _style=style)))

        return thead

    def _make_field_header(self, field: Field, field_index: int, sort_order: str) -> tuple[str, HTMLElement]:
        up = I(**self.param.grid_class_style.get("grid-sorter-icon-up"))
        dw = I(**self.param.grid_class_style.get("grid-sorter-icon-down"))

        key = str(field.orderby) if isinstance(field, Column) else f"{field.tablename}.{field.name}"

        heading = (
            self.param.headings[field_index]
            if field_index < len(self.param.headings)
            else getattr(field, "label", title(field.name))
        )
        #  add the sort order query parm
        sort_query_parms = dict(self.query_parms)

        attrs = {}
        if isinstance(field, FieldVirtual):
            col = SPAN(heading)
        elif key == sort_order:
            sort_query_parms["orderby"] = "~" + key
            url = URL(self.endpoint, "select", vars=sort_query_parms)
            attrs = self.attributes_plugin.link(url=url)
            col = A(heading, up, **attrs)
        else:
            sort_query_parms["orderby"] = key
            url = URL(self.endpoint, "select", vars=sort_query_parms)
            attrs = self.attributes_plugin.link(url=url)
            col = A(heading, dw if "~" + key == sort_order else "", **attrs)
        return key, col

    def _make_field(self, row: Row, field: Field, _field_index: int) -> HTMLElement:
        """Render a field.

        if only 1 table in the query, the no table name needed when getting the row value - however, if there
        are multiple tables in the query (self.use_tablename == True) then we need to use the tablename as well
        when accessing the value in the row object

        the row object sent in can take
        :param row:
        :param field:
        :return:
        """
        if self.use_tablename:
            row = row[field.tablename]
        field_value = field.f(row) if isinstance(field, FieldVirtual) else row[field.name]
        key = f"{field.tablename}.{field.name}"
        # custom formatter overwrites represent
        if key in self.formatters:
            formatter = self.formatters.get(key)
        # else if represent provided use it
        elif field.represent:
            formatter = field.represent
        # else fallback on the formatter for the type
        elif field.type in self.formatters_by_type:
            formatter = self.formatters_by_type.get(field.type)
        # else fallback to default
        else:
            formatter = self.formatters_by_type.get("default")
        # allow 1 (value) or 2 (value + row) args
        try:
            formatted_value = formatter(field_value, row)  # type: ignore
        except TypeError:
            formatted_value = formatter(field_value) if formatter else field_value

        grid_cell_type = str(field.type).split(":")[0].split("(")[0]
        class_type = f"grid-cell-type-{grid_cell_type}"
        class_col = f" grid-col-{key.replace('.', '_')}"
        classes = join_classes(
            self.param.grid_class_style.classes.get("grid-td"),
            self.param.grid_class_style.classes.get(class_type),
            class_col,
        )
        td = TD(
            formatted_value,
            **clean_sc(
                _class=classes,
                _style=(
                    self.param.grid_class_style.styles.get(class_type)
                    or self.param.grid_class_style.styles.get("grid-td")
                ),
            ),
        )

        return td

    def _make_table_body(self) -> HTMLElement:
        tbody = TBODY()
        if not self.rows:
            return tbody

        for row in self.rows:
            #  find the row id - there may be nested tables....
            if not (self.use_tablename and self.tablename in row and "id" not in row):
                self.use_tablename = False

            key = f"{self.tablename}.__row"
            if fmt := self.formatters.get(key):
                extra_class = fmt(row)["_class"]
                extra_style = fmt(row)["_style"]
            else:
                extra_class = ""
                extra_style = ""
            tr = TR(
                _role="row",
                **clean_sc(
                    _class=join_classes(self.param.grid_class_style.classes.get("grid-tr"), extra_class),
                    _style=join_styles([self.param.grid_class_style.styles.get("grid-tr"), extra_style]),
                ),
            )
            #  add all the fields to the row
            for index, column in enumerate(self.param.columns):
                if isinstance(column, (Field, FieldVirtual)):
                    field = column
                    if field.readable and (field.type != "id" or self.param.show_id):
                        tr.append(self._make_field(row, field, index))
                elif isinstance(column, Column):
                    classes = self.param.grid_class_style.classes.get(
                        column.td_class_style,
                        self.param.grid_class_style.classes.get("grid-td"),
                    )
                    style = self.param.grid_class_style.styles.get(
                        column.td_class_style,
                        self.param.grid_class_style.styles.get("grid-td"),
                    )
                    tr.append(
                        TD(
                            column.represent(row),
                            **clean_sc(_class=classes, _style=style),
                        )
                    )

            tbody.append(tr)

        return tbody

    def make_action_buttons(self, row: Row) -> HTMLElement:  # noqa C901: this is too complex
        # but forked from py4web so harder to rewrite right now (todo)
        """Build the row-level action buttons for the grid."""
        cat = CAT()
        row_id = row[self.param.field_id] if self.param.field_id else row.id
        if self.param.pre_action_buttons and len(self.param.pre_action_buttons) > 0:
            for btn in self.param.pre_action_buttons:
                if callable(btn):
                    # a button can be a callable, to indicate whether or not a button should
                    # be displayed. call the function with the row object
                    btn = btn(row)
                    if btn is None:
                        # if None was returned, no button is available for this row: ignore this value in the
                        # list
                        continue
                attrs = (
                    self.attributes_plugin.confirm(message=self.T(btn.message))
                    if btn.message and btn.message != ""
                    else btn.__dict__.get("attrs", {})
                )

                cat.append(
                    self._make_action_button(
                        url=btn.url,
                        button_text=self.T(btn.text),
                        icon=btn.icon,
                        additional_classes=btn.additional_classes,
                        additional_styles=btn.__dict__.get("additional_styles"),
                        override_classes=btn.__dict__.get("override_classes"),
                        override_styles=btn.__dict__.get("override_styles"),
                        message=btn.message,
                        row_id=row_id if btn.append_id else None,
                        name=btn.__dict__.get("name"),
                        row=row,
                        ignore_attribute_plugin=(
                            btn.ignore_attribute_plugin if "ignore_attribute_plugin" in btn.__dict__ else False
                        ),
                        **attrs,
                    )
                )

        if self.is_readable(row):
            details_url = self.param.details if isinstance(self.param.details, str) else self.endpoint + "/details"

            details_url += f"/{row_id}?{self.referrer}"
            cat.append(
                self._make_action_button(
                    url=details_url,
                    button_text=self.T(self.param.details_action_button_text),
                    icon="fa-id-card",
                    name="grid-details-button",
                )
            )
        if self.is_editable(row):
            edit_url = self.param.editable if isinstance(self.param.editable, str) else self.endpoint + "/edit"
            edit_url += f"/{row_id}?{self.referrer}"
            cat.append(
                self._make_action_button(
                    url=edit_url,
                    button_text=self.T(self.param.edit_action_button_text),
                    icon="fa-edit",
                    name="grid-edit-button",
                    _disabled=not self.is_editable(row),
                )
            )
        if self.is_deletable(row):
            delete_url = self.param.deletable if isinstance(self.param.deletable, str) else self.endpoint + "/delete"
            delete_url += f"/{row_id}?{self.referrer}"
            attrs = self.attributes_plugin.confirm(message=self.T("Are you sure you want to delete?"))
            cat.append(
                self._make_action_button(
                    url=delete_url,
                    button_text=self.T(self.param.delete_action_button_text),
                    icon="fa-trash",
                    additional_classes="confirmation",
                    message="Delete record",
                    name="grid-delete-button",
                    _disabled=not self.is_deletable(row),
                    **attrs,
                )
            )

        if self.param.post_action_buttons and len(self.param.post_action_buttons) > 0:
            for btn in self.param.post_action_buttons:
                if callable(btn):
                    # a button can be a callable, to indicate whether or not a button should
                    # be displayed. call the function with the row object
                    btn = btn(row)
                    if btn is None:
                        # if None was returned, no button is available for this row: ignore this value in the
                        # list
                        continue
                attrs = (
                    self.attributes_plugin.confirm(message=self.T(btn.message))
                    if btn.message and btn.message != ""
                    else btn.__dict__.get("attrs", {})
                )
                cat.append(
                    self._make_action_button(
                        url=btn.url,
                        button_text=self.T(btn.text),
                        icon=btn.icon,
                        additional_classes=btn.additional_classes,
                        additional_styles=btn.__dict__.get("override_styles"),
                        override_classes=btn.__dict__.get("override_classes"),
                        override_styles=btn.__dict__.get("override_styles"),
                        message=btn.message,
                        row_id=row_id if btn.append_id else None,
                        name=btn.__dict__.get("name"),
                        row=row,
                        ignore_attribute_plugin=(
                            btn.ignore_attribute_plugin if "ignore_attribute_plugin" in btn.__dict__ else False
                        ),
                        **attrs,
                    )
                )

        return DIV(cat, _class="grid-action-stack")

    def _make_table_pager(self) -> HTMLElement:
        pager = DIV(**self.param.grid_class_style.get("grid-pagination"))
        previous_page_number = None
        for page_number in self.iter_pages(self.current_page_number, self.number_of_pages):
            pager_query_parms = dict(self.query_parms)
            pager_query_parms["page"] = page_number
            # if there is a gat add a spacer
            if previous_page_number and page_number - previous_page_number > 1:
                pager.append(SPAN("...", _style="margin:0 10px;"))
            is_current = self.current_page_number == page_number
            page_name = "grid-pagination-button-current" if is_current else "grid-pagination-button"
            attrs = self.attributes_plugin.link(url=URL(self.endpoint, "select", vars=pager_query_parms))
            pager.append(
                A(
                    page_number,
                    **self.param.grid_class_style.get(page_name),
                    _role="button",
                    **attrs,
                )
            )
            previous_page_number = page_number
        return pager

    def _make_table(self) -> HTMLElement:  # noqa C901: this is too complex
        # but forked from py4web so harder to rewrite right now (todo)
        html = DIV(**self.param.grid_class_style.get("grid-wrapper"))
        grid_header = DIV(**self.param.grid_class_style.get("grid-header"))

        #  build the New button if needed
        if self.param.create and self.param.create != "":
            create_url = self.param.create if isinstance(self.param.create, str) else self.endpoint + "/new"

            create_url += f"?{self.referrer}"

            grid_header.append(
                self._make_action_button(
                    create_url,
                    self.T(self.param.new_action_button_text),
                    "fa-plus",
                    icon_size="normal",
                    override_classes=self.param.grid_class_style.classes.get("grid-new-button", ""),
                    override_styles=self.param.grid_class_style.styles.get("grid-new-button"),
                )
            )
        if self.param.header_elements and len(self.param.header_elements) > 0:
            for element in self.param.header_elements:
                if isinstance(element, str):
                    html.append(XML(element))
                elif callable(element):
                    grid_header.append(element())
                else:
                    override_classes = element.__dict__.get("override_classes", None)
                    if not override_classes:
                        override_classes = (
                            self.param.grid_class_style.classes.get("grid-header-element", "")
                            + f" {element.additional_classes}"
                        )
                    override_styles = element.__dict__.get("override_styles", None)
                    if not override_styles:
                        override_styles = (
                            self.param.grid_class_style.styles.get("grid-trailer-element", "")
                            + f" {element.__dict__.get('additional_styles')}"
                        )
                    grid_header.append(
                        self._make_action_button(
                            url=element.url,
                            button_text=self.T(element.text),
                            icon=element.icon,
                            icon_size="normal",
                            additional_classes=element.additional_classes,
                            additional_styles=element.__dict__.get("additional_styles"),
                            override_classes=override_classes,
                            override_styles=override_styles,
                            message=element.message,
                            name=element.__dict__.get("name"),
                            ignore_attribute_plugin=element.ignore_attribute_plugin,
                            **element.__dict__.get("attrs", {}),
                        )
                    )

        #  build the search form if provided
        if self.param.search_form:
            grid_header.append(self._make_search_form())
        elif self.param.search_queries and len(self.param.search_queries) > 0:
            grid_header.append(self._make_default_form())

        html.append(grid_header)

        table = TABLE(**self.param.grid_class_style.get("grid-table"))

        # build the header
        table.append(self._make_table_header())

        #  build the rows
        table.append(self._make_table_body())

        #  add the table to the html
        html.append(DIV(table, **self.param.grid_class_style.get("grid-table-wrapper")))

        #  add the row counter information
        footer = DIV(**self.param.grid_class_style.get("grid-footer"))

        row_count = DIV(**self.param.grid_class_style.get("grid-info"))
        (
            row_count.append(
                str(self.T("Displaying rows %s thru %s of %s"))
                % (
                    self.page_start + 1 if self.number_of_pages > 1 else 1,
                    self.page_end if self.page_end < self.total_number_of_rows else self.total_number_of_rows,
                    self.total_number_of_rows,
                )
            )
            if self.number_of_pages > 0
            else row_count.append(self.T("No rows to display"))
        )
        footer.append(row_count)

        #  build the pager
        if self.number_of_pages > 1:
            footer.append(self._make_table_pager())

        html.append(footer)

        if self.param.footer_elements and len(self.param.footer_elements) > 0:
            for element in self.param.footer_elements:
                if isinstance(element, str):
                    html.append(XML(element))
                elif callable(element):
                    html.append(element())
                else:
                    override_classes = element.__dict__.get("override_classes", None)
                    if not override_classes:
                        override_classes = (
                            self.param.grid_class_style.classes.get("grid-footer-element", "")
                            + f" {element.additional_classes}"
                        )
                    override_styles = element.__dict__.get("override_styles", None)
                    if not override_styles:
                        override_styles = (
                            self.param.grid_class_style.styles.get("grid-footer-element", "")
                            + f" {element.__dict__.get('additional_styles')}"
                        )
                    html.append(
                        self._make_action_button(
                            url=element.url,
                            button_text=self.T(element.text),
                            icon=element.icon,
                            icon_size="normal",
                            additional_classes=element.additional_classes,
                            additional_styles=element.__dict__.get("additional_styles"),
                            override_classes=override_classes,
                            override_styles=override_styles,
                            message=element.message,
                            name=element.__dict__.get("name"),
                            ignore_attribute_plugin=element.ignore_attribute_plugin,
                            **element.__dict__.get("attrs", {}),
                        )
                    )

        return html

    def render(self) -> HTMLElement | FormWithParam:
        """Build the query table.

        :return: html representation of the table or the py4web Form object
        """
        if self.action in ("new", "details", "edit"):
            assert self.form
            return self.form
        else:
            return self._make_table()

    def xml(self) -> str:
        """Render the grid as XML."""
        return self.render().xml()

    def __str__(self) -> str:
        """Render the grid as a string."""
        return str(self.xml())

    def data(self) -> Row | None:
        """Get the record that is being edited or displayed.

        :return: DAL record of the record being edited
        """
        return self.db[self.tablename](self.record_id) if self.tablename and self.record_id else None

    def get_tablenames(self, *args: t.Any) -> list[str]:
        """Return the table names used by this grid."""
        return list(self.db._adapter.tables(*args).keys())

    def is_join(self) -> bool:
        """Return whether the grid query spans more than one table."""
        items = [self.param.query]
        if self.param.left is not None:
            if isinstance(self.param.left, (list, tuple)):
                items += [item for item in self.param.left if item]
            else:
                items += [self.param.left]
        return len(self.get_tablenames(*items)) > 1

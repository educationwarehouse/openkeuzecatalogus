"""Archive table rendering helpers."""

import itertools
import typing as t

from py4web.utils.grid import GridClassStyleBootstrap5
from pydal.objects import Row
from typedal.types import Field
from yatl import TAGGER as HTMLElement
from yatl.helpers import BUTTON, DIV, SPAN, TABLE, TD, TH, TR, XML, A, I

from shared_code.data_model.mixins.effdt import EffdtTable
from shared_code.util.html import convert_attrs

from .actions import GridActionButton, post_action_form


def merge_class_style(*classes: str, class_style_dict: dict[str, str] | None = None) -> dict[str, str]:
    """Merge extra CSS classes and styles into a style mapping."""
    class_styles = class_style_dict or {}

    return {
        "_class": " ".join(filter(None, [*classes, class_styles.get("_class", "")])),
        "_style": class_styles.get("_style", ""),
    }


def _build_action_buttons(
    row: Row, action_buttons: t.Iterable[t.Callable[[Row], GridActionButton]], class_style: GridClassStyleBootstrap5
) -> HTMLElement:
    buttons = (btn(row) for btn in action_buttons)
    td_style = class_style.get("grid-td-buttons")
    rendered_buttons = []

    for btn in buttons:
        element = BUTTON if btn.method == "POST" else A
        attrs = {"type": "submit"} if btn.method == "POST" else {"href": btn.url}

        button = element(
            (I(_class=f"fa {btn.icon}") if btn.icon else ""),
            SPAN(XML(f"&nbsp;{btn.text}") if btn.text else ""),
            _class=btn.override_classes or btn.additional_classes or class_style.classes["grid-details-button"],
            _style=btn.override_styles or btn.additional_styles or "",
            _title=btn.text,
            **(convert_attrs(attrs) | btn.attrs),
        )

        if btn.method == "POST":
            button = post_action_form(button, btn.url, message=btn.message)

        rendered_buttons.append(button)

    return TD(
        *rendered_buttons,
        _class=td_style.get("_class", ""),
        _style=td_style.get("_style", ""),
    )


def _build_tr(
    row: Row,
    changed_fields: list[Field],
    class_style: GridClassStyleBootstrap5,
    action_buttons: t.Sequence[t.Callable[[Row], GridActionButton]],
) -> HTMLElement:
    tds = []

    if action_buttons:
        tds.append(_build_action_buttons(row, action_buttons, class_style=class_style))

    for field in changed_fields:
        val = str(row[field])
        tds.append(TD(val, **class_style.get("grid-td")))

    return TR(*tds, **class_style.get("grid-tr"))


def _highlight_archive_changes(
    rows: list[tuple[Row, HTMLElement]],
    changed_fields: list[Field],
    id_field: Field,
    latest_id: str | int,
    offset: int,
) -> None:
    """Mark the current version and values changed from the preceding version."""
    for (this_data, this_tr), (next_data, _) in itertools.pairwise(rows):
        if str(this_data[id_field.name]) == str(latest_id):
            current_class = this_tr.attributes.get("_class", "")
            this_tr["_class"] = f"{current_class} current-row".strip()

        for col_idx, field in enumerate(changed_fields, start=offset):
            if str(this_data[field]) != str(next_data[field]):
                td = this_tr[col_idx]
                td["_class"] = f"{td.attributes.get('_class', '')} highlight".strip()

    last_data, last_tr = rows[-1]
    if last_data[id_field.name] == latest_id:
        current_class = last_tr.attributes.get("_class", "")
        last_tr["_class"] = f"{current_class} current-row".strip()


def build_archive_table(
    table_ed: type[EffdtTable],
    latest_id: str | int,
    keyfieldname: str = "gid",
    db: t.Any | None = None,
    archive_fields: t.Iterable[Field] = (),
    class_style: GridClassStyleBootstrap5 | None = None,
    action_buttons: t.Iterable[t.Callable[[Row], GridActionButton]] = (),
) -> HTMLElement:
    """Build the archive table for a single effective-dated row."""
    class_style = class_style or GridClassStyleBootstrap5()
    action_buttons = tuple(action_buttons)

    db = db or table_ed._db
    id_field = table_ed._id
    assert id_field, "every table has an ID field"
    assert db, "can't continue without a db"

    keyfield = getattr(table_ed, keyfieldname)
    current_record = table_ed(latest_id)

    archive_fields = list(archive_fields) or list(table_ed)

    htable = db(keyfield == current_record[keyfieldname]).select(*archive_fields, orderby=~table_ed.effdt)
    if not htable:
        return DIV("No historical data available.", **class_style.get("grid-wrapper"))

    # Detect which fields changed
    changed_fields = [
        field for field in archive_fields if len({str(row[field]) for row in htable}) > 1
    ] or archive_fields

    htable = db(keyfield == current_record[keyfieldname]).select(table_ed._id, *changed_fields, orderby=~table_ed.effdt)

    headers = [
        TH(field.label if hasattr(field, "label") else field.name, **class_style.get("grid-th"))
        for field in changed_fields
    ]
    if action_buttons:
        headers.insert(0, TH("", **class_style.get("grid-th")))

    rows = []
    for row in htable:
        tr = _build_tr(row, changed_fields, action_buttons=action_buttons, class_style=class_style)
        rows.append((row, tr))

    offset = 1 if action_buttons else 0
    _highlight_archive_changes(rows, changed_fields, id_field, latest_id, offset)

    table_html = TABLE(
        TR(*headers, **class_style.get("grid-tr")),
        *(tr for _, tr in rows),
        **class_style.get("grid-table"),
    )

    return DIV(
        DIV(
            DIV(
                table_html,
                **merge_class_style(
                    "archive-table",
                    "archive-container",
                    class_style_dict=class_style.get("grid-table-wrapper"),
                ),
            ),
        ),
        **class_style.get("grid-wrapper"),
    )


__all__ = [
    "build_archive_table",
]

"""Reusable row controls for drag ordering in admin grids."""

import typing as t

from typedal import TypedField
from typedal.types import Field
from yatl import TAGGER as HTMLElement
from yatl.helpers import BUTTON, SPAN, I

from py4web import request
from shared_code.util.html import convert_attrs


def reordered_gids(current_gids: list[str], submitted_gids: list[str]) -> list[str]:
    """Reorder a visible subset while preserving the positions of other rows."""
    if (
        not submitted_gids
        or len(submitted_gids) != len(set(submitted_gids))
        or not set(submitted_gids) <= set(current_gids)
    ):
        raise ValueError("Ongeldige volgorde")

    positions = [index for index, gid in enumerate(current_gids) if gid in submitted_gids]
    reordered = current_gids[:]
    for position, gid in zip(positions, submitted_gids, strict=True):
        reordered[position] = gid
    return reordered


def reorder_handle(field: Field | TypedField[t.Any], gid: str, label: str) -> HTMLElement:
    """Render a drag handle, disabled when another column controls the grid order."""
    selected_order = str(request.query.get("orderby") or "")
    field_order = field.longname
    disabled = bool(selected_order and selected_order != field_order)
    hint = (
        "Rangschikken kan alleen in de standaardvolgorde."
        if disabled
        else "Sleep of gebruik de pijltjestoetsen om te rangschikken"
    )
    return SPAN(
        BUTTON(
            I(_class="okl-icon okl-icon--dots-six-vertical", _aria_hidden="true"),
            _type="button",
            _class="btn btn-sm btn-outline-secondary grid-reorder-handle",
            **convert_attrs(
                {
                    "data-gid": gid,
                    "data-reorder-label": label,
                    "data-reorder-hint": hint,
                    "aria-label": f"Verplaats {label}. {hint}",
                    "disabled": disabled,
                }
            ),
        ),
        _title=hint,
    )

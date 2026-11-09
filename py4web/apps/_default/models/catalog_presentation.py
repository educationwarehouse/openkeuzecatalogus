"""Human-readable presentation of the existing public catalogue payloads."""

import datetime as dt
import json
import os
import typing as t
from urllib.parse import urlencode

from common.models import db
from typedal import TypedTable
from yatl.helpers import DIV, LI, SPAN, TAG, UL, A

from shared_code.data_model.representers import dutch_bool
from shared_code.util.html import catalog_external_url

CatalogPresentationKind = t.Literal["product", "method", "supplier"]
CATALOG_MODELS: dict[CatalogPresentationKind, str] = {
    "product": "Product",
    "method": "Method",
    "supplier": "Supplier",
}
UNREPRESENTED = object()
DL = TAG.dl
DT = TAG.dt
DD = TAG.dd

COMPARISON_LINK_LABELS = {
    "image_url": "Bekijk afbeelding",
    "preview": "Bekijk inkijkexemplaar",
    "preview_url": "Bekijk inkijkexemplaar",
    "preview_link": "Bekijk inkijkexemplaar",
    "sample_copies": "Bekijk inkijkexemplaar",
    "sample_copies_link": "Bekijk inkijkexemplaar",
    "preview_digital_environment": "Bekijk digitale omgeving",
    "demo_environment_link": "Bekijk demo",
    "more_information": "Meer informatie bij de aanbieder",
    "website": "Bekijk website",
}


class CatalogField(t.TypedDict):
    label: str
    value: t.Any


def _catalog_table(entity_kind: CatalogPresentationKind) -> type[TypedTable]:
    table = db.find_model(CATALOG_MODELS[entity_kind])
    if table is None:
        raise LookupError(f"Unknown catalogue model for {entity_kind!r}")
    return table


def _represented_field_value(
    value: t.Any,
    entity_kind: CatalogPresentationKind | None,
    field_name: str | None,
) -> t.Any:
    """Use the data model's maintained representer when one is available."""
    if not entity_kind or not field_name or isinstance(value, (t.Mapping, list, tuple)):
        return UNREPRESENTED
    table = _catalog_table(entity_kind)
    field = getattr(table, field_name, None)
    represent = getattr(field, "represent", None)
    if not callable(represent):
        return UNREPRESENTED
    try:
        return represent(value, None)
    except TypeError:
        return represent(value)


def display_catalog_value(
    value: t.Any,
    entity_kind: CatalogPresentationKind | None = None,
    field_name: str | None = None,
    compact_links: bool = False,
) -> t.Any:
    """Render structured public values without interpreting content as HTML."""
    if value is None or value == "" or value == [] or value == {}:
        return SPAN("Niet opgegeven", _class="okl-data-empty")
    elif isinstance(value, bool):
        return dutch_bool(value)
    represented = _represented_field_value(value, entity_kind, field_name)
    if represented is not UNREPRESENTED:
        return represented
    elif isinstance(value, dt.date):
        return value.strftime("%d-%m-%Y")
    elif isinstance(value, t.Mapping):
        return DL(
            *[DIV(DT(str(key).replace("_", " ")), DD(display_catalog_value(item))) for key, item in value.items()],
            _class="okl-data-list",
        )
    elif isinstance(value, (list, tuple)):
        return UL(*[LI(display_catalog_value(item)) for item in value], _class="okl-data-values")
    text = str(value)
    if link := catalog_external_url(text):
        return A(
            "Meer informatie" if compact_links else text,
            _href=link,
            _target="_blank",
            _rel="noopener noreferrer",
            _title=text,
            _class="okl-button okl-button--secondary" if compact_links else None,
        )
    return text


def catalog_fields(payload: t.Mapping[str, t.Any], entity_kind: CatalogPresentationKind) -> list[CatalogField]:
    """Keep every supplied public field, using the model's maintained labels."""
    table = _catalog_table(entity_kind)
    return [
        {
            "label": str(getattr(getattr(table, name, None), "label", None) or name.replace("_", " ").capitalize()),
            "value": display_catalog_value(payload[name], entity_kind=entity_kind, field_name=name),
        }
        for name in payload
    ]


def catalog_report_url(heading: str) -> str:
    """Encode the complete catalogue title as one mail subject parameter."""
    recipient = os.environ["CATALOG_REPORT_EMAIL"]
    return f"mailto:{recipient}?" + urlencode({"subject": f"Fout in {heading}"})


def comparison_link_label(field_name: str, field_label: str) -> str:
    """Return the maintained action label for a comparison URL."""
    return COMPARISON_LINK_LABELS.get(field_name, f"Bekijk {field_label.lower()}")


def display_vision_properties(properties: str) -> t.Any:
    """Present the comparison module's serialized property values as readable data."""
    try:
        value = json.loads(properties)
    except TypeError, ValueError:
        value = properties
    return display_catalog_value(value)

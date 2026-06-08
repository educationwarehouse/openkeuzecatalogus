"""Base table definitions and shared fields."""

import typing as t
import uuid

from pydal.validators import IS_IN_SET, IS_INT_IN_RANGE, IS_NULL_OR
from typedal import Ref, TypeDAL, TypedTable, relationship
from typedal.fields import TextField, TypedField, UUIDField
from typedal.mixins import TimestampsMixin

from shared_code.data_model.mixins import EffdtFields
from shared_code.data_model.mixins.markdown import MarkdownMixin
from shared_code.data_model.representers import comma_separated, dutch_date
from shared_code.data_model.validators.is_uuid import IS_UUID

if t.TYPE_CHECKING:  # pragma: no cover
    from shared_code.data_model import Supplier  # noqa F401; used by relationship()


class BaseTable(TypedTable, TimestampsMixin, MarkdownMixin):
    """Base table for all tables in the platform.

    Adds gid field, timestamps and markdown conversion to all tables.
    """

    gid = UUIDField(default=uuid.uuid4, writable=False, requires=IS_UUID(), filter_out=str)

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure field representers when the table is defined."""
        super().__on_define__(db)

        # otherwise py4web will represent it with a `document.write()` in US format which is ugly and also breaks htmx
        cls.created_at.represent = dutch_date
        cls.updated_at.represent = dutch_date


def physical_digital_mix_nederlands(value: str, *_: t.Any) -> str:
    """Represent physical/digital mix values in Dutch."""
    return {
        "digital": "Digitaal",
        "physical": "Fysiek",
        "mix": "Mix",
    }.get((value or "").lower(), "Onbekend")


class SharedProductField(EffdtFields):
    """Shared fields used by product-like tables."""

    olid = TypedField(str, label="OLID", unique=True)
    supplier_gid = UUIDField(filter_out=str, label="Aanbieder GID")
    levels = TypedField(list[str], label="Niveaus", represent=comma_separated)
    subjects = TypedField(list[str], label="Vakken", represent=comma_separated)
    image_url = TypedField(str, label="Afbeelding URL")
    description = TextField(label="Beschrijving")
    available = TypedField(
        str,
        label="Beschikbaar",
        requires=IS_IN_SET(
            (
                "leverbaar",
                "niet leverbaar",
                "onbekend",
                "nog niet leverbaar",
                "beperkt leverbaar",
                "binnenkort niet meer leverbaar",
                "verwijderd",
            )
        ),
    )
    import_error_codes = TypedField(list[str], label="Importfouten", represent=comma_separated)
    edition = TypedField(int, label="Editie", requires=IS_NULL_OR(IS_INT_IN_RANGE()))
    authors = TypedField(list[str], label="Auteurs", represent=comma_separated)
    language = TypedField(str, label="Taal")
    license_duration = TypedField(str, label="Licentieduur")
    physical_digital_mix = TypedField(str, label="Fysiek/Digitaal Mix", represent=physical_digital_mix_nederlands)
    digital_folio_mix = TypedField(list[str], label="Digitaal Folio Mix", represent=comma_separated)
    browser = TypedField(list[str], label="Browser", represent=comma_separated)
    devices = TypedField(list[str], label="Apparaten", represent=comma_separated)
    operating_systems = TypedField(list[str], label="Besturingssystemen", represent=comma_separated)
    elo_integration = TextField(label="ELO Integratie")
    more_information = TypedField(str, label="Meer Informatie")
    priority = TypedField(int, label="Prioriteit (2: volledig, 1: aanvullend)")
    bouw = TypedField(list[str], label="Bouw", represent=comma_separated)
    tto = TypedField(bool, label="TTO")

    supplier = relationship(Ref["Supplier"], condition=lambda self, supplier: self.supplier_gid == supplier.gid)

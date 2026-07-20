"""Base table definitions and shared fields."""

import typing as t

from pydal.validators import IS_IN_SET, IS_INT_IN_RANGE, IS_NULL_OR
from typedal import Ref, relationship
from typedal.fields import TextField, TypedField, UUIDField

from shared_code.data_model.mixins.effdt.mixin import EffdtFields
from shared_code.data_model.representers import comma_separated

if t.TYPE_CHECKING:
    from shared_code.data_model import Supplier  # noqa F401; used by relationship()


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
    supplier_gid = UUIDField(filter_out=str, label="Aanbieder GID", notnull=True)
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

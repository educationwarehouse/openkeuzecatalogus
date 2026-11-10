"""Persisted weights for relevance-ranked catalogue searches."""

from pydal.validators import IS_IN_SET, IS_INT_IN_RANGE, IS_NULL_OR
from typedal import TypedField

from shared_code.data_model.tables.base import EffdtTable

SEARCH_RANK_SCORE_NAMES = {
    "exact": "Exacte overeenkomst",
    "prefix": "Begint met",
    "contains": "Bevat",
    "trigram": "Vergelijkbare spelling",
}
SEARCH_RANK_SECTION_TITLES = {
    "name": "Naamovereenkomsten",
    "related": "Gerelateerde gegevens",
    "identifier": "Identificaties",
}


class SearchRankWeightEd(EffdtTable):
    """Effective-dated source configuration for one ranking rule."""

    entity_kind = TypedField(
        str,
        length=10,
        label="Catalogustype",
        requires=IS_IN_SET({"product": "Producten", "method": "Methodes"}),
    )
    section = TypedField(
        str,
        length=20,
        label="Sectie",
        requires=IS_IN_SET(SEARCH_RANK_SECTION_TITLES),
    )
    sort_order = TypedField(int, label="Volgorde", default=0, requires=IS_INT_IN_RANGE(0, 1001))
    label = TypedField(
        str,
        length=100,
        label="Waarop wordt gematcht",
        comment="Het veld waarop de zoekterm is gevonden, zoals productnaam, leveranciersnaam of methode-OLID.",
    )
    key = TypedField(
        str,
        length=40,
        label="Regelsleutel",
        comment="Vaste technische sleutel voor een door de applicatie ondersteunde rankingregel.",
    )
    source_field = TypedField(
        str,
        length=100,
        label="Zoekveld",
        comment="Veldnaam waarop wordt gezocht. Bij een gerelateerde regel is dit een veld van de gerelateerde tabel.",
    )
    foreign_key = TypedField(
        str | None,
        length=100,
        label="Lokale koppeling",
        comment="Alleen voor gerelateerde regels: het lokale veld dat naar de gerelateerde tabel verwijst.",
    )
    related_table = TypedField(
        str | None,
        length=100,
        label="Gerelateerde tabel",
        comment="Alleen voor gerelateerde regels: het datamodel van de tabel waarin wordt gezocht.",
    )
    related_key = TypedField(
        str | None,
        length=100,
        label="Gerelateerde koppeling",
        comment="Alleen voor gerelateerde regels: het veld dat terugverwijst naar de lokale rij.",
    )
    exact = TypedField(int | None, label="Exact", requires=IS_NULL_OR(IS_INT_IN_RANGE(0, 5001)))
    prefix = TypedField(int | None, label="Begint met", requires=IS_NULL_OR(IS_INT_IN_RANGE(0, 5001)))
    contains = TypedField(int | None, label="Bevat", requires=IS_NULL_OR(IS_INT_IN_RANGE(0, 5001)))
    trigram = TypedField(int | None, label="Vergelijkbare spelling", requires=IS_NULL_OR(IS_INT_IN_RANGE(0, 5001)))


class SearchRankWeight(SearchRankWeightEd):
    """Current score configuration for a fixed ranking rule."""

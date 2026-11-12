"""Tests for Kennisnet catalogue admin-grid helpers."""

import csv
import io
import json
from codecs import BOM_UTF8
from pathlib import Path
from types import SimpleNamespace

import pytest
from apps.admin.models.kennisnet_catalogue import (
    format_kennisnet_product_value,
    kennisnet_catalogue_search_fields,
    kennisnet_product_cell,
    kennisnet_products_export_orderby,
    kennisnet_publisher_search_fields,
    matched_supplier_names,
    matched_supplier_versions,
    publisher_match_badge,
    publisher_match_status,
)
from apps.admin.models.kennisnet_import_export import KENNISNET_PRODUCT_CSV_COLUMNS, build_kennisnet_products_csv

from shared_code.modules.scrapers.kennisnet_catalogue import (
    KennisnetCatalogueProduct,
    KennisnetCataloguePublisher,
    _catalogue_database,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({}, "\N{EN DASH}"),
        ({"value": None}, "\N{EN DASH}"),
        ({"value": ""}, "\N{EN DASH}"),
        ({"value": []}, "\N{EN DASH}"),
        ({"value": {}}, "\N{EN DASH}"),
        ({"value": True}, "true"),
        ({"value": False}, "false"),
        ({"value": 0}, "0"),
        ({"value": 12.5}, "12.5"),
        ({"value": "Café"}, "Café"),
        ({"value": {"title": "Café"}}, '{\n  "title": "Café"\n}'),
        ({"value": ["boek", "digitaal"]}, '[\n  "boek",\n  "digitaal"\n]'),
    ],
)
def test_optional_product_columns_preserve_values(source: dict[str, object], expected: str) -> None:
    """Optional columns keep zero, false and nested source data distinguishable from empty values."""
    assert format_kennisnet_product_value(source, "value") == expected


def test_kennisnet_catalogue_search_fields_use_cached_publishers_and_versions(tmp_path: Path) -> None:
    """Catalogue and publisher grids expose their cached selector values."""
    database = _catalogue_database(database_path=tmp_path / "catalogue.sqlite")
    KennisnetCatalogueProduct.insert(
        publisher="Alpha",
        name="Alpha product",
        product_id="alpha-1",
        version="v2",
        status="available",
        product_type="digital",
        source_json="{}",
    )
    KennisnetCatalogueProduct.insert(
        publisher="Beta",
        name="Beta product",
        product_id="beta-1",
        version="v1",
        status="available",
        product_type="book",
        source_json="{}",
    )
    KennisnetCataloguePublisher.insert(publisher="Alpha", version="v2")
    KennisnetCataloguePublisher.insert(publisher="Beta", version="v1")
    database.commit()

    catalogue_fields = kennisnet_catalogue_search_fields()
    publisher_fields = kennisnet_publisher_search_fields({"Alpha": [], "Beta": []})

    assert [field.name for field in catalogue_fields] == ["publisher", "version"]
    assert [field.name for field in publisher_fields] == ["version", "status"]
    assert {value for value, _label in catalogue_fields[0].requires.options()} == {"", "Alpha", "Beta"}
    assert {value for value, _label in catalogue_fields[1].requires.options()} == {"", "v1", "v2"}
    assert {value for value, _label in publisher_fields[0].requires.options()} == {"", "v1", "v2"}


@pytest.mark.parametrize(
    ("version", "suppliers", "expected_status"),
    [
        ("v2", [], "Onbekend"),
        (
            "v2",
            [SimpleNamespace(endpoint_type="edu-v", endpoint_base_url="https://catalogus.edu-v.kennisnet.nl/v2/")],
            "Versie komt overeen",
        ),
        ("v2", [SimpleNamespace(endpoint_type="edu-v", endpoint_base_url=None)], "Geen Edu-V versie geconfigureerd"),
        (
            "v2",
            [SimpleNamespace(endpoint_type="edu-v", endpoint_base_url="https://catalogus.edu-v.kennisnet.nl/v1/")],
            "Versie wijkt af",
        ),
        ("v2", [SimpleNamespace(endpoint_type="edu-v-kennisnet-v2", endpoint_base_url=None)], "Versie komt overeen"),
    ],
)
def test_publisher_match_status_and_badge_cover_each_local_supplier_state(
    version: str,
    suppliers: list[SimpleNamespace],
    expected_status: str,
) -> None:
    """Publisher status and its badge agree for matching, missing, and mismatched versions."""
    assert publisher_match_status(version, suppliers) == expected_status
    assert expected_status in str(publisher_match_badge(version, suppliers))


def test_matched_supplier_display_helpers_deduplicate_names_and_versions() -> None:
    """Publisher rows show concise local supplier names and configured Edu-V versions."""
    suppliers = [
        SimpleNamespace(
            name="Alpha", endpoint_type="edu-v", endpoint_base_url="https://catalogus.edu-v.kennisnet.nl/v2/"
        ),
        SimpleNamespace(
            name="Alpha", endpoint_type="edu-v", endpoint_base_url="https://catalogus.edu-v.kennisnet.nl/v2/"
        ),
        SimpleNamespace(name="Beta", endpoint_type="none", endpoint_base_url=None),
    ]

    assert matched_supplier_names(suppliers) == "Alpha, Beta"
    assert matched_supplier_versions(suppliers) == "v2"
    assert matched_supplier_names([]) == "Onbekend"
    assert matched_supplier_versions([]) == "Niet geconfigureerd"


def test_products_csv_exports_raw_values_and_neutralizes_formulas(tmp_path: Path) -> None:
    """The export keeps raw JSON and booleans, falls back to the stored type and escapes formula-like text."""
    database = _catalogue_database(database_path=tmp_path / "catalogue.sqlite")
    source = {"type": "digital", "forSale": True, "subjects": ["rekenen"], "shortDescription": "\t=HYPERLINK(1)"}
    KennisnetCatalogueProduct.insert(
        publisher="=Alpha",
        name="Alpha product",
        product_id="alpha-1",
        version="v2",
        status="available",
        product_type="digital",
        source_json=json.dumps(source),
    )
    KennisnetCatalogueProduct.insert(
        publisher="Beta",
        name="Beta product",
        product_id="beta-1",
        version="v1",
        status="available",
        product_type="book",
        # The column is NOT NULL in SQLite, so a product without source data stores an empty value.
        source_json="",
    )
    database.commit()

    content = build_kennisnet_products_csv(KennisnetCatalogueProduct.orderby(KennisnetCatalogueProduct.id).collect())

    assert content.startswith(BOM_UTF8)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert list(rows[0]) == KENNISNET_PRODUCT_CSV_COLUMNS
    assert rows[0]["publisher"] == "'=Alpha"
    assert rows[0]["shortDescription"] == "'\t=HYPERLINK(1)"
    assert rows[0]["forSale"] == "true"
    assert rows[0]["subjects"] == '["rekenen"]'
    assert json.loads(rows[0]["source_json"]) == source
    assert rows[1]["type"] == "book"
    assert rows[1]["source_json"] == ""


@pytest.mark.parametrize(
    ("sort_order", "expected"),
    [
        ("", ["publisher", "name"]),
        ("kennisnet_catalogue_product.version", ["version"]),
        ("~kennisnet_catalogue_product.status", ["status DESC"]),
        ("kennisnet_catalogue_product.source_json", ["publisher", "name"]),
        ("other_table.name", ["publisher", "name"]),
    ],
)
def test_products_export_follows_only_sortable_grid_columns(
    tmp_path: Path, sort_order: str, expected: list[str]
) -> None:
    """The export reuses the grid's column sort and ignores fields the grid cannot sort on."""
    _catalogue_database(database_path=tmp_path / "catalogue.sqlite")

    orderby = kennisnet_products_export_orderby(sort_order)

    # A descending expression renders with quoted identifiers ("table"."field" DESC); plain fields do not.
    assert [str(item).replace('"', "").removeprefix("kennisnet_catalogue_product.") for item in orderby] == expected


def test_empty_product_cell_reads_as_empty_value_for_screen_readers() -> None:
    """The visual dash is hidden from assistive technology and replaced by readable text."""
    html = str(kennisnet_product_cell({}, key="shortDescription"))

    assert 'aria-hidden="true">\N{EN DASH}</span>' in html
    assert '<span class="visually-hidden">Lege waarde</span>' in html
    assert "aria_label" not in html

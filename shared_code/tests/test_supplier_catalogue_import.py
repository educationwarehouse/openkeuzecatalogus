"""Catalogue participation CSV parsing, confirmed imports and public grouping."""

import typing as t
import uuid

import pytest
from typedal import TypeDAL

from shared_code.data_model import MethodEd, ProductEd, Supplier, SupplierEd
from shared_code.modules.suppliers.catalogue import catalogue_participation_groups
from shared_code.modules.suppliers.catalogue_import import (
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    CatalogueImportRow,
    CatalogueImportSelection,
    apply_catalogue_import,
    propose_supplier_matches,
    read_catalogue_csv,
)

HEADER = "officiele_naam,edu_v_naam,status"


def import_row(name: str, status: str = "soon") -> CatalogueImportRow:
    """Build a parsed source row without going through the CSV reader."""
    return CatalogueImportRow(
        name=name,
        import_name=f"Officieel {name}",
        aliases=[name],
        suggested_gid="",
        status=status,
        candidates=[],
    )


@pytest.fixture()
def imported_suppliers(db_per_file: TypeDAL) -> t.Iterator[list[str]]:
    """Remove every version of suppliers that an import created or updated."""
    gids: list[str] = []

    yield gids

    if gids:
        SupplierEd.where(SupplierEd.gid.belongs(gids)).delete()
    db_per_file.commit()


def test_csv_reader_accepts_commas_and_ignores_extra_columns_and_bom() -> None:
    """A UTF-8 export with a byte order mark and unrelated columns yields only the three known values."""
    content = f"﻿opmerking,{HEADER}\nnvt,Uitgeverij A,Uitgever A,Binnenkort gedeeld\n".encode()

    rows = read_catalogue_csv(content)

    assert [(row["import_name"], row["name"], row["status"]) for row in rows] == [
        ("Uitgeverij A", "Uitgever A", "soon")
    ]


def test_csv_reader_accepts_semicolons_from_dutch_excel() -> None:
    """Dutch Excel separates columns with semicolons and may quote names that contain commas."""
    content = 'officiele_naam;edu_v_naam;status\n"Uitgeverij B, Breda";Uitgever B;In gesprek\n'.encode()

    rows = read_catalogue_csv(content)

    assert [(row["import_name"], row["status"]) for row in rows] == [("Uitgeverij B, Breda", "in_conversation")]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "maximaal 5 MB"),
        ("officiele_naam,status\nA,Onbekend\n".encode(), "verplicht"),
        (f"{HEADER}\nA,A,Misschien\n".encode(), "kies Beschikbaar"),
        (f"{HEADER}\nA,A,Onbekend\na,B,Onbekend\n".encode(), "dubbele officiële naam"),
        (f"{HEADER}\n,,\n".encode(), "geen aanbieders"),
        ("officiele_naam,edu_v_naam,status\nA,A,Onbekend\n".encode("utf-16"), "UTF-8"),
    ],
)
def test_csv_reader_rejects_invalid_files_with_a_readable_reason(content: bytes, message: str) -> None:
    """Every rejected upload explains what the administrator has to correct."""
    with pytest.raises(ValueError, match=message):
        read_catalogue_csv(content)


def test_csv_reader_enforces_the_row_and_size_limits() -> None:
    """Uploads are bounded both by the number of suppliers and by their size in bytes."""
    rows = "".join(f"Aanbieder {index},Aanbieder {index},Onbekend\n" for index in range(MAX_ROWS + 1))

    with pytest.raises(ValueError, match="maximaal 1000"):
        read_catalogue_csv(f"{HEADER}\n{rows}".encode())

    with pytest.raises(ValueError, match="maximaal 5 MB"):
        read_catalogue_csv(b"x" * (MAX_UPLOAD_BYTES + 1))


def test_matches_are_proposed_only_for_unambiguous_names(supplier_factory: t.Callable[..., Supplier]) -> None:
    """One match is preselected, no match proposes a new supplier and several matches need a choice."""
    suffix = uuid.uuid4().hex[:8]
    single = supplier_factory(name=f"Uitgever Één {suffix}", email_domains=[f"one-{suffix}.example.test"])
    twin_a = supplier_factory(name=f"Tweeling {suffix}", email_domains=[f"twin-a-{suffix}.example.test"])
    twin_b = supplier_factory(name=f"tweeling-{suffix}", email_domains=[f"twin-b-{suffix}.example.test"])
    rows = [import_row(f"uitgever een {suffix}"), import_row(f"Tweeling {suffix}"), import_row(f"Nieuw {suffix}")]

    propose_supplier_matches(rows, [single, twin_a, twin_b])

    assert rows[0]["suggested_gid"] == str(single.gid)
    assert rows[1]["suggested_gid"] == ""
    assert set(rows[1]["candidates"]) == {str(twin_a.gid), str(twin_b.gid)}
    assert rows[2]["suggested_gid"] == "new"


def test_import_creates_updates_and_skips_while_preserving_supplier_history(
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    imported_suppliers: list[str],
) -> None:
    """A confirmed import adds versions for changed suppliers and leaves unchanged ones alone."""
    suffix = uuid.uuid4().hex[:8]
    changed = supplier_factory(name=f"Gewijzigd {suffix}", email_domains=[f"changed-{suffix}.example.test"])
    same = supplier_factory(name=f"Gelijk {suffix}", email_domains=[f"same-{suffix}.example.test"])
    imported_suppliers.extend([str(changed.gid), str(same.gid)])
    rows = [import_row(changed.name), import_row(same.name), import_row(f"Nieuw {suffix}"), import_row("Overslaan")]
    selections = [
        CatalogueImportSelection(target=str(changed.gid), status="in_conversation"),
        CatalogueImportSelection(target=str(same.gid), status="unknown"),
        CatalogueImportSelection(target="new", status="soon"),
        CatalogueImportSelection(target="skip", status="soon"),
    ]

    result = apply_catalogue_import(db_per_file, rows, selections, actor="test/catalogue-import")
    db_per_file.commit()
    created = Supplier.where(Supplier.name == f"Nieuw {suffix}").collect().first()
    if created:
        imported_suppliers.append(str(created.gid))

    assert result == {"created": 1, "updated": 1, "unchanged": 1, "skipped": 1}
    assert created is not None
    assert created.catalogue_participation_status == "soon"
    assert Supplier.where(Supplier.gid == changed.gid).collect().first().catalogue_participation_status == (
        "in_conversation"
    )
    assert SupplierEd.where(SupplierEd.gid == changed.gid).count() == 2
    assert SupplierEd.where(SupplierEd.gid == same.gid).count() == 1


@pytest.mark.parametrize("duplicate", ("existing", "new"))
def test_import_rejects_two_rows_for_the_same_supplier_without_writing(
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    imported_suppliers: list[str],
    duplicate: str,
) -> None:
    """Linking two source rows to one supplier, or creating one name twice, fails before any version is added."""
    suffix = uuid.uuid4().hex[:8]
    supplier = supplier_factory(name=f"Dubbel {suffix}", email_domains=[f"double-{suffix}.example.test"])
    imported_suppliers.append(str(supplier.gid))
    target = str(supplier.gid) if duplicate == "existing" else "new"
    rows = [import_row(f"Nieuw dubbel {suffix}"), import_row(f"Nieuw dubbel {suffix}")]
    selections = [CatalogueImportSelection(target=target, status="soon") for _row in rows]
    before = SupplierEd.count()

    with pytest.raises(ValueError, match="dezelfde aanbieder|bestaat al"):
        apply_catalogue_import(db_per_file, rows, selections, actor="test/catalogue-import")
    db_per_file.rollback()

    assert SupplierEd.count() == before


def test_public_products_place_a_supplier_under_available_regardless_of_its_status(
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    imported_suppliers: list[str],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Actual public products outrank the imported expectation; other statuses keep their own group.

    The supplier cleanup is requested before the method and product factories, so those rows are removed first.
    """
    suffix = uuid.uuid4().hex[:8]
    publishing = supplier_factory(name=f"Publiceert {suffix}", email_domains=[f"publishing-{suffix}.example.test"])
    expecting = supplier_factory(name=f"Verwacht {suffix}", email_domains=[f"expecting-{suffix}.example.test"])
    imported_suppliers.extend([str(publishing.gid), str(expecting.gid)])
    rows = [import_row(publishing.name), import_row(expecting.name)]
    selections = [
        CatalogueImportSelection(target=str(publishing.gid), status="in_conversation"),
        CatalogueImportSelection(target=str(expecting.gid), status="soon"),
    ]
    apply_catalogue_import(db_per_file, rows, selections, actor="test/catalogue-import")
    db_per_file.commit()

    method = method_factory(supplier_gid=publishing.gid, olid=f"participation-{suffix}", name=f"Methode {suffix}")
    product_factory(
        supplier_gid=publishing.gid,
        method_gid=method.gid,
        olid=f"participation-product-{suffix}",
        name=f"Product {suffix}",
    )

    groups = {
        group["key"]: {supplier["gid"] for supplier in group["suppliers"]} for group in catalogue_participation_groups()
    }

    assert str(publishing.gid) in groups["available"]
    assert str(publishing.gid) not in groups["in_conversation"]
    assert str(expecting.gid) in groups["soon"]

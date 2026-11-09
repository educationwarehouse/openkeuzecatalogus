"""Integration tests for the temporary legacy method OLID upgrade during imports.

Delete this file together with the upgrade path described in `_legacy_method_targets`.
"""

import datetime as dt
import hashlib
import uuid

import pytest
from slugify import slugify
from typedal import TypeDAL

from shared_code.data_model import (
    DecisionMaterialSelection,
    DecisionProcess,
    DecisionTeamEd,
    Method,
    MethodEd,
    SupplierEd,
)
from shared_code.modules.scrapers.eduv import BaseEduVImporter
from shared_code.modules.scrapers.flow import ImportFlow
from shared_code.modules.scrapers.types import ImportPriority
from shared_code.util.olid import generate, generate_supplier_olid


def _legacy_method_olid(key: str) -> str:
    """Return the OLID that the generator produced before hashing the original key."""
    identifier = generate("method", key).rpartition("#")[0]
    return identifier + "#" + hashlib.shake_256(identifier.encode()).hexdigest(2)


def _supplier() -> SupplierEd:
    gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=gid,
        name=f"Legacy OLID Supplier {uuid.uuid4().hex[:8]}",
        olid=generate_supplier_olid(gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    assert supplier is not None
    return supplier


def _import_methods(db: TypeDAL, supplier: SupplierEd, olids: list[str]) -> None:
    ImportFlow.with_injected(db=db).import_methods_and_products(
        methods=[
            {"supplier_gid": supplier.gid, "olid": olid, "name": f"Methode {index}", "available": "leverbaar"}
            for index, olid in enumerate(olids)
        ],
        products=[],
        prio=ImportPriority.IMPORTER_OK,
        last_saved_by="pytest.scrapers.legacy-olids",
        mark_removed=False,
    )


@pytest.mark.parametrize(
    ("publisher", "family"),
    [("Uitgever", "foo-bar"), ("uitgever", "Rekenen & Taal"), ("Malmberg", "pluspunt 4")],
)
def test_method_keys_never_equal_their_slug(publisher: str, family: str) -> None:
    """Current method OLIDs never use the legacy hash, so a legacy hash in the database is always stale."""
    key = BaseEduVImporter._method_key(publisher, family)

    assert key != slugify(key)
    assert generate("method", key) != _legacy_method_olid(key)


def test_import_upgrades_legacy_method_olid(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """An incoming OLID upgrades the matching legacy method, keeping its GID, history and selections."""
    assert migrated_db_per_file is None
    key = f"uitgever {uuid.uuid4().hex[:8]}:rekenen & taal"
    legacy_olid = _legacy_method_olid(key)
    new_olid = generate("method", key)

    supplier = _supplier()
    method = MethodEd.insert(supplier_gid=supplier.gid, olid=legacy_olid, name="Rekenen & Taal")
    assert method is not None

    team = DecisionTeamEd.insert(name="Legacy OLID team", location_gid=str(uuid.uuid4()), last_saved_by="pytest")
    assert team is not None
    process = DecisionProcess.insert(team_gid=team.gid, schoolyear="2026-2027", start_date=dt.date.today())
    assert process is not None
    selection = DecisionMaterialSelection.insert(process_gid=process.gid, name="Rekenen & Taal", olid=legacy_olid)
    assert selection is not None
    db_per_file.commit()

    _import_methods(db_per_file, supplier, [new_olid])

    assert Method.where(Method.olid == new_olid).first_or_fail().gid == method.gid
    assert not Method.where(Method.olid == legacy_olid).exists()
    assert MethodEd.where(MethodEd.gid == method.gid, MethodEd.olid == legacy_olid).exists()
    assert DecisionMaterialSelection.where(id=selection.id).first_or_fail().olid == new_olid


def test_import_rejects_competing_identifiers_for_one_legacy_method(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Two incoming keys that shared one legacy OLID cannot both claim the existing method."""
    assert migrated_db_per_file is None
    publisher = f"uitgever {uuid.uuid4().hex[:8]}"
    first_olid = generate("method", f"{publisher}:foo & bar")
    second_olid = generate("method", f"{publisher}:foo + bar")
    legacy_olid = _legacy_method_olid(f"{publisher}:foo & bar")
    assert legacy_olid == _legacy_method_olid(f"{publisher}:foo + bar")

    supplier = _supplier()
    method = MethodEd.insert(supplier_gid=supplier.gid, olid=legacy_olid, name="Foo Bar")
    assert method is not None
    db_per_file.commit()

    with pytest.raises(ValueError, match="Ambiguous incoming identifiers"):
        _import_methods(db_per_file, supplier, [first_olid, second_olid])
    db_per_file.rollback()

    assert Method.where(Method.olid == legacy_olid).first_or_fail().gid == method.gid


def test_import_leaves_legacy_method_when_new_olid_has_its_own_method(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """A legacy method is not merged into another method that already owns the incoming OLID."""
    assert migrated_db_per_file is None
    key = f"uitgever {uuid.uuid4().hex[:8]}:taal & lezen"
    legacy_olid = _legacy_method_olid(key)
    new_olid = generate("method", key)

    supplier = _supplier()
    legacy_method = MethodEd.insert(supplier_gid=supplier.gid, olid=legacy_olid, name="Oude methode")
    assert legacy_method is not None
    current_method = MethodEd.insert(supplier_gid=supplier.gid, olid=new_olid, name="Huidige methode")
    assert current_method is not None
    db_per_file.commit()

    _import_methods(db_per_file, supplier, [new_olid])

    assert Method.where(Method.olid == legacy_olid).first_or_fail().gid == legacy_method.gid
    assert Method.where(Method.olid == new_olid).first_or_fail().gid == current_method.gid

"""Regression tests for effective-dated JSON grid imports."""

import uuid

import pytest
from common.models import db
from common.models.grid_support.json_import import JsonImport, JsonImportConfig
from psycopg2 import IntegrityError

from shared_code.data_model import Supplier, SupplierEd
from shared_code.data_model.constants import ROLE_SUPPLIER


def _unique_olid() -> str:
    """Return an OLID that cannot collide with another test run."""
    return f"json-import-{uuid.uuid4()}"


def _ensure_supplier_role() -> None:
    """Create the supplier role when the isolated test database lacks it."""
    if db.identity(email=ROLE_SUPPLIER):
        return

    db.auth.raw_rbac.add_group(ROLE_SUPPLIER, ROLE_SUPPLIER, [])
    db.commit()


def _json_import(**callbacks: object) -> JsonImport[Supplier]:
    """Build a JSON importer for the supplier grid."""
    return JsonImport(
        db,
        table=Supplier,
        config=JsonImportConfig("suppliers"),
        endpoint="/admin/suppliers",
        actor="pytest",
        query=Supplier.id > 0,
        **callbacks,
    )


def test_json_import_dispatches_callbacks_for_each_change_type() -> None:
    """JSON imports should use the grid's insert, update, and archive callbacks."""
    _ensure_supplier_role()
    existing = SupplierEd.insert(name="Existing supplier", olid=_unique_olid())
    archived = SupplierEd.insert(name="Archived supplier", olid=_unique_olid())
    db.commit()

    changes: list[tuple[str, str]] = []
    importer = _json_import(
        after_insert=[lambda row: changes.append(("insert", row.gid))],
        after_update=[lambda row: changes.append(("update", row.gid))],
        after_delete=[lambda row: changes.append(("delete", row.gid))],
    )
    importer.rows = [
        {"values": {"name": "New supplier", "olid": _unique_olid()}},
        {"values": {"gid": existing.gid, "name": "Updated supplier"}},
        {"values": {"gid": archived.gid, "effstatus": False}},
    ]

    importer.apply()

    assert [action for action, _ in changes] == ["insert", "update", "delete"]
    assert changes[1][1] == existing.gid
    assert changes[2][1] == archived.gid


def test_json_import_rolls_back_all_rows_when_a_later_supplier_insert_fails() -> None:
    """A failed multi-row import must not commit supplier rows from earlier rows."""
    _ensure_supplier_role()
    duplicate_olid = _unique_olid()
    importer = _json_import()
    importer.rows = [
        {"values": {"name": "First supplier", "olid": duplicate_olid}},
        {"values": {"name": "Duplicate supplier", "olid": duplicate_olid}},
    ]

    with pytest.raises(IntegrityError):
        importer.apply()

    assert SupplierEd.where(SupplierEd.olid == duplicate_olid).count() == 0

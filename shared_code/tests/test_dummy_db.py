"""Basic smoke tests for dummy database wiring."""

import pytest

from typedal import TypeDAL

from shared_code.data_model import MethodEd, Product, ProductEd, SupplierEd, update_effectivedated
from shared_code.data_model.constants import ROLE_SUPPLIER
from shared_code.util.olid import generate_supplier_olid


# note: db from conftest


def test_db_has_tables(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Verify core models exist and table iteration does not crash."""
    assert migrated_db_per_file is None
    assert db_per_file
    assert db_per_file.find_model("Product")
    assert not db_per_file.find_model("FakeModel")

    for table in db_per_file:
        # doesn't need to have values but at least shouldn't crash:
        db_per_file(table).count()


def test_product_ed_effstatus_roundtrip(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Write effstatus via ORM and verify it via SQL and ORM."""
    assert migrated_db_per_file is None

    dummy_supplier = SupplierEd.insert(name="DummySupplier", olid="supplier-dummy-1")
    dummy_method = MethodEd.insert(supplier_gid=dummy_supplier.gid)

    row_true = ProductEd.insert(olid="product-ed-effstatus-true", available="leverbaar", effstatus=True, supplier_gid=dummy_supplier.gid, method_gid=dummy_method.gid)
    row_false = ProductEd.insert(olid="product-ed-effstatus-false", available="leverbaar", effstatus=False, supplier_gid=dummy_supplier.gid, method_gid=dummy_method.gid)
    db_per_file.commit()

    rows_sql = db_per_file.executesql(
        "SELECT id, effstatus FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    effstatus_sql_by_id = {row["id"]: row["effstatus"] for row in rows_sql}
    assert effstatus_sql_by_id[row_true.id] is True
    assert effstatus_sql_by_id[row_false.id] is False
    true_rows_sql = db_per_file.executesql(
        "SELECT id FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) AND effstatus = true ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    false_rows_sql = db_per_file.executesql(
        "SELECT id FROM product_ed WHERE id IN (%(id_true)s, %(id_false)s) AND effstatus = false ORDER BY id ASC;",
        placeholders={"id_true": row_true.id, "id_false": row_false.id},
        as_dict=True,
    )
    assert [row["id"] for row in true_rows_sql] == [row_true.id]
    assert [row["id"] for row in false_rows_sql] == [row_false.id]

    rows_orm = ProductEd.where(ProductEd.id.belongs((row_true.id, row_false.id))).collect()
    effstatus_orm_by_id = {row.id: row.effstatus for row in rows_orm}
    assert effstatus_orm_by_id[row_true.id] is True
    assert effstatus_orm_by_id[row_false.id] is False


def test_product_insert_delegates_to_effective_dated_history(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Inserting into Product should be rejected until model inserts are supported."""
    assert migrated_db_per_file is None

    supplier = SupplierEd.insert(name="Product Insert Supplier", olid="product-insert-supplier")
    method = MethodEd.insert(
        name="Product Insert Method",
        olid="product-insert-method",
        available="leverbaar",
        supplier_gid=supplier.gid,
    )
    db_per_file.commit()

    with pytest.raises(PermissionError):
        Product.insert(
            name="Product Insert Smoke Test",
            olid="product-insert-smoke-test",
            available="leverbaar",
            supplier_gid=supplier.gid,
            method_gid=method.gid,
        )


def test_supplier_ed_insert_generates_olid_from_gid(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Supplier inserts should derive OLID from the generated gid."""
    assert migrated_db_per_file is None

    supplier = SupplierEd.insert(name="Generated Supplier")
    db_per_file.commit()

    assert supplier.olid == generate_supplier_olid(supplier.gid)


def test_supplier_ed_insert_creates_supplier_rbac_group(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac,
) -> None:
    """Supplier inserts should create the matching supplier RBAC group."""
    assert migrated_db_per_file is None

    supplier = SupplierEd.insert(name="RBAC Supplier", email_domains=["rbac-supplier.example.test"], endpoint_type="none")
    db_per_file.commit()

    assert seeded_rbac.get_group(str(supplier.gid)) is not None
    assert seeded_rbac.has_membership(str(supplier.gid), ROLE_SUPPLIER)


def test_supplier_ed_effdt_rename_updates_supplier_group_name(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    seeded_rbac,
) -> None:
    """Effective-dated supplier updates should keep the RBAC group name in sync."""
    assert migrated_db_per_file is None

    supplier = SupplierEd.insert(name="Original Supplier", email_domains=["rename-supplier.example.test"], endpoint_type="none")
    db_per_file.commit()

    update_effectivedated(
        db_per_file,
        SupplierEd,
        SupplierEd.gid == supplier.gid,
        {"name": "Renamed Supplier"},
        last_saved_by="pytest",
    )
    db_per_file.commit()

    group = seeded_rbac.get_group(str(supplier.gid))
    assert group is not None
    assert group["name"] == "Renamed Supplier"

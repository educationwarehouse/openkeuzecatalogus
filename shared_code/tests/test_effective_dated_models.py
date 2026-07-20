"""Integration tests for effective-dated model sync."""
import uuid
from abc import ABC
import datetime as dt

import pytest
from edwh_migrate import ViewMigrationManager
from typedal import TypeDAL

from shared_code.data_model import Method, MethodEd, Product, ProductEd, SupplierEd
from shared_code.data_model.mixins.effdt.helpers import ed_restore_by_id, model_to_ed, update_effectivedated
from shared_code.migrations.migration_support.core import (
    create_effdted_model_view_with_prio_v4,
    no_triggers,
    rebuild_all_materialized_tables_v1,
)
from shared_code.util.exceptions import Required
from shared_code.util.time import timezone_aware_timedelta, utcnow


class MockMigrationManager(ViewMigrationManager, ABC):
    def should_run(self):
        return True


class AlphaTestModelMigration(MockMigrationManager):
    """Test-local wrapper that installs dynamic model objects via `up()`."""

    uses = ()

    def up(self) -> None:
        create_effdted_model_view_with_prio_v4(self.db, "alpha_test")

    def down(self) -> None:
        _drop_dynamic_derived_objects(self.db, "alpha_test")


class BetaTestModelMigration(MockMigrationManager):
    """Test-local wrapper that installs dynamic model objects via `up()`."""

    uses = ()

    def up(self) -> None:
        create_effdted_model_view_with_prio_v4(self.db, "beta_test")

    def down(self) -> None:
        _drop_dynamic_derived_objects(self.db, "beta_test")


def _create_dynamic_ed_table(db: TypeDAL, table: str) -> None:
    db.executesql(f"""
    CREATE TABLE {table}_ed (
        id SERIAL PRIMARY KEY,
        gid UUID NOT NULL DEFAULT uuidv4(),
        olid TEXT NOT NULL,
        name TEXT NOT NULL,
        effdt TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CLOCK_TIMESTAMP(),
        effstatus BOOLEAN NOT NULL DEFAULT TRUE,
        prio INTEGER NOT NULL DEFAULT 0
    );
    """)


def _drop_dynamic_derived_objects(db: TypeDAL, table: str) -> None:
    model = f"{table}_model"
    effdt = f"{table}_ed"

    db.executesql(f"""
    DROP TRIGGER IF EXISTS refresh_{model}_trigger ON {effdt};
    DROP TRIGGER IF EXISTS {model}_update_trigger ON {effdt};
    DROP FUNCTION IF EXISTS get_active_{table}(uuid);
    DROP FUNCTION IF EXISTS apply_change_{model}();
    DROP FUNCTION IF EXISTS rebuild_{model}();
    DROP TABLE IF EXISTS {model};
    """)


def _drop_dynamic_ed_table(db: TypeDAL, table: str) -> None:
    effdt = f"{table}_ed"

    db.executesql(f"""
    DROP TABLE IF EXISTS {effdt};
    """)


def test_executesql_placeholders_prevent_sql_injection(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Show that SQL interpolation is injectable while placeholders are not."""
    assert migrated_db_per_file is None

    dummy_method_gid = str(uuid.uuid4())
    dummy_supplier_gid = str(uuid.uuid4())

    ProductEd.insert(olid="sql-injection-safe-1", name="SQL Injection Safe 1", available="leverbaar", method_gid=dummy_method_gid, supplier_gid=dummy_supplier_gid)
    db_per_file.commit()

    malicious_olid = "missing' OR 1=1 --"

    unsafe_count = db_per_file.executesql(
        f"SELECT COUNT(*) FROM product_ed WHERE olid = '{malicious_olid}';",
    )[0][0]

    safe_count_placeholders = db_per_file.executesql(
        "SELECT COUNT(*) FROM product_ed WHERE olid = %(olid)s;",
        placeholders={"olid": malicious_olid},
    )[0][0]

    safe_count_tstring = db_per_file.executesql(
        t"SELECT COUNT(*) FROM product_ed WHERE olid = {malicious_olid};",
    )[0][0]

    safe_count_orm = Product.where(olid=malicious_olid).count()

    assert unsafe_count > 0
    assert safe_count_placeholders == safe_count_tstring == safe_count_orm == 0


def test_product_ed_insert_populates_product_model(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """An insert into `product_ed` should populate `product_model` for the same gid."""
    assert migrated_db_per_file is None

    dummy_supplier_gid = str(uuid.uuid4())
    dummy_method_gid = str(uuid.uuid4())

    inserted_row = ProductEd.insert(
        olid="product-model-sync-test",
        name="Product Model Sync Test",
        available="leverbaar",
        method_gid=dummy_method_gid,
        supplier_gid=dummy_supplier_gid,
    )
    db_per_file.commit()

    row = Product.where(Product.gid == inserted_row.gid).first_or_fail()

    assert row.id == inserted_row.id
    assert str(row.gid) == str(inserted_row.gid)
    assert row.olid == "product-model-sync-test"
    assert row.name == "Product Model Sync Test"
    assert row.effstatus is True

    ProductEd.insert(
        gid=inserted_row.gid,
        olid="product-model-sync-test-lower",
        name="Product Model Sync Test Lower",
        available="leverbaar",
        effdt=utcnow() - dt.timedelta(hours=1),
        method_gid=dummy_method_gid,
        supplier_gid=dummy_supplier_gid,
    )
    db_per_file.commit()

    row = Product.where(Product.gid == inserted_row.gid).first_or_fail()

    assert row.id == inserted_row.id
    assert str(row.gid) == str(inserted_row.gid)
    assert row.olid == "product-model-sync-test"
    assert row.name == "Product Model Sync Test"
    assert row.effstatus is True

    ProductEd.insert(
        gid=inserted_row.gid,
        olid="product-model-sync-test-higher",
        name="Product Model Sync Test Higher",
        available="leverbaar",
        method_gid=dummy_method_gid,
        supplier_gid=dummy_supplier_gid,
    )
    db_per_file.commit()

    row = Product.where(Product.gid == inserted_row.gid).first_or_fail()

    assert str(row.gid) == str(inserted_row.gid)
    assert row.olid == "product-model-sync-test-higher"
    assert row.name == "Product Model Sync Test Higher"
    assert row.effstatus is True


def test_method_ed_higher_prio_wins_when_effdt_matches(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Raw SQL inserts should refresh `method` via triggers using prio before effdt."""
    assert migrated_db_per_file is None

    dummy_supplier_gid = str(uuid.uuid4())

    gid = str(uuid.uuid4())
    fixed_effdt = dt.datetime(2026, 1, 1, 12, 0, 0)

    db_per_file.executesql(
        """
        INSERT INTO method_ed (gid, olid, name, available, effdt, prio, supplier_gid)
            VALUES (%(gid)s, %(olid)s, %(name)s, %(available)s, %(effdt)s, %(prio)s, %(supplier_gid)s);
        """,
        placeholders={
            "gid": gid,
            "olid": "method-prio-low",
            "name": "Method Prio Low",
            "available": "leverbaar",
            "effdt": fixed_effdt,
            "prio": 1,
            "supplier_gid": dummy_supplier_gid,
        },
    )
    # `placeholders` work the same way as t-strings (escaped)
    db_per_file.executesql(
        """
        INSERT INTO method_ed (gid, olid, name, available, effdt, prio, supplier_gid)
            VALUES (%(gid)s, %(olid)s, %(name)s, %(available)s, %(effdt)s, %(prio)s, %(supplier_gid)s);
        """,
        placeholders={
            "gid": gid,
            "olid": "method-prio-high",
            "name": "Method Prio High",
            "available": "leverbaar",
            "effdt": fixed_effdt,
            "prio": 5,
            "supplier_gid": dummy_supplier_gid,
        },
    )
    db_per_file.commit()

    row = Method(gid=gid)

    assert row
    assert str(row.gid) == gid
    assert row.olid == "method-prio-high"
    assert row.name == "Method Prio High"
    assert row.effstatus is True

    rows_sql = db_per_file.executesql(
        t"SELECT gid, olid, name, prio, effdt FROM method_model method WHERE {gid = };",
        as_dict=True,
    )
    assert rows_sql == [
        {
            "gid": row.gid,
            "olid": "method-prio-high",
            "name": "Method Prio High",
            "prio": 5,
            "effdt": fixed_effdt,
        }
    ]


def test_no_triggers_requires_targeted_and_global_rebuilds(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Disabling triggers should defer `_model` sync until explicit rebuild helpers run."""
    assert migrated_db_per_file is None

    supplier_gid = str(uuid.uuid4())
    product_gid = str(uuid.uuid4())
    method_gid = str(uuid.uuid4())
    effdt = dt.datetime(2026, 1, 2, 12, 0, 0)

    with no_triggers(db_per_file):
        MethodEd.insert(
            gid=method_gid,
            olid="method-no-triggers-test",
            name="Method No Triggers Test",
            available="leverbaar",
            effdt=effdt,
            supplier_gid=supplier_gid,
        )
        ProductEd.insert(
            gid=product_gid,
            olid="product-no-triggers-test",
            name="Product No Triggers Test",
            available="leverbaar",
            effdt=effdt,
            method_gid=method_gid,
            supplier_gid=supplier_gid,
        )
        db_per_file.commit()

    assert Product.where(Product.gid == product_gid).count() == 0
    assert Method.where(Method.gid == method_gid).count() == 0

    db_per_file.executesql("SELECT rebuild_product_model();")
    db_per_file.commit()

    product_row = Product.where(Product.gid == product_gid).first_or_fail()

    assert str(product_row.gid) == product_gid
    assert product_row.olid == "product-no-triggers-test"
    assert product_row.name == "Product No Triggers Test"
    assert Method.where(Method.gid == method_gid).count() == 0

    rebuilt_tables = rebuild_all_materialized_tables_v1(db_per_file)

    assert "product_model" in rebuilt_tables
    assert "method_model" in rebuilt_tables

    method_row = Method.where(Method.gid == method_gid).first_or_fail()

    assert str(method_row.gid) == method_gid
    assert method_row.olid == "method-no-triggers-test"
    assert method_row.name == "Method No Triggers Test"


def test_effective_dated_helper_functions_use_real_tables(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Exercise the shared effdt helper functions against real product rows."""
    assert migrated_db_per_file is None

    assert model_to_ed(Product) is ProductEd

    supplier_gid = str(uuid.uuid4())
    method_gid = str(uuid.uuid4())
    product_gid = str(uuid.uuid4())
    original_effdt = dt.datetime(2026, 1, 3, 12, 0, 0)

    SupplierEd.insert(
        gid=supplier_gid,
        name="Effdt Helper Supplier",
        logo_url="https://example.com/supplier.svg",
        olid="effdt-helper-supplier",
        status_visions="compleet",
        effdt=original_effdt,
    )
    MethodEd.insert(
        gid=method_gid,
        supplier_gid=supplier_gid,
        olid="effdt-helper-method",
        name="Effdt Helper Method",
        available="leverbaar",
        effdt=original_effdt,
    )

    inserted = ProductEd.insert(
        gid=product_gid,
        supplier_gid=supplier_gid,
        method_gid=method_gid,
        olid="effdt-helper-001",
        name="Effdt Helper Original",
        available="leverbaar",
        effdt=original_effdt,
    )
    db_per_file.commit()

    restored = ed_restore_by_id(ProductEd, inserted.id, "unit.test")
    assert restored is not None
    assert str(restored["gid"]) == product_gid
    assert restored["olid"] == "effdt-helper-001"
    assert restored["name"] == "Effdt Helper Original"
    assert restored["last_saved_by"] == "unit.test"

    product_row = Product.where(Product.gid == product_gid).first_or_fail()
    product_row.update_record(name="Effdt Helper Updated")
    db_per_file.commit()

    updated_product = Product.where(Product.gid == product_gid).first_or_fail()
    assert updated_product.name == "Effdt Helper Updated"
    assert ProductEd.where(ProductEd.gid == product_gid).count() == 3  # original + restored + updated

    latest_ed_row = ProductEd.where(ProductEd.gid == product_gid).select(orderby=~ProductEd.id).first_or_fail()
    assert latest_ed_row.name == "Effdt Helper Updated"
    assert latest_ed_row.effstatus is True
    assert latest_ed_row.effdt >= restored["effdt"]

    product_row = Product.where(Product.gid == product_gid).first_or_fail()
    product_row.delete_record()
    db_per_file.commit()

    assert Product.where(Product.gid == product_gid).count() == 0
    assert ProductEd.where(ProductEd.gid == product_gid).count() == 4  # ^ + deleted

    deleted_ed_row = ProductEd.where(ProductEd.gid == product_gid).select(orderby=~ProductEd.id).first_or_fail()
    assert deleted_ed_row.effstatus is False
    assert deleted_ed_row.name == "Effdt Helper Updated"
    assert deleted_ed_row.effdt >= latest_ed_row.effdt

    # restore from deleted before we can update again:
    _restored_again = ed_restore_by_id(ProductEd, inserted.id, "unit.test")

    helper_base_effdt = utcnow() + dt.timedelta(minutes=5)
    prio_effdt = helper_base_effdt
    prio_id = update_effectivedated(
        db_per_file,
        ProductEd,
        ProductEd.gid == product_gid,
        new_values={
            "supplier_gid": supplier_gid,
            "method_gid": method_gid,
            "olid": "effdt-helper-001",
            "name": "Effdt Helper Original",
            "available": "leverbaar",
        },
        prio=5,
        effdt=prio_effdt,
        last_saved_by="prio.test",
    )
    prio_row = db_per_file.executesql(
        "SELECT prio, last_saved_by, effdt FROM product_ed WHERE id = %(id)s;",
        placeholders={"id": prio_id},
        as_dict=True,
    )[0]
    assert prio_row["prio"] == 5
    assert prio_row["last_saved_by"] == "prio.test"
    assert timezone_aware_timedelta(prio_row["effdt"], prio_effdt) == dt.timedelta(0)

    delete_effdt = helper_base_effdt + dt.timedelta(minutes=1)
    delete_id = update_effectivedated(
        db_per_file,
        ProductEd,
        ProductEd.gid == product_gid,
        delete=True,
        effdt=delete_effdt,
        last_saved_by="delete.test",
    )

    delete_row = db_per_file.executesql(
        "SELECT gid, effstatus, last_saved_by, effdt FROM product_ed WHERE id = %(id)s;",
        placeholders={"id": delete_id},
        as_dict=True,
    )[0]
    assert delete_row["effstatus"] is False
    assert delete_row["last_saved_by"] == "delete.test"
    assert timezone_aware_timedelta(delete_row["effdt"], delete_effdt) == dt.timedelta(0)

    with pytest.raises(NotImplementedError, match="Cannot update a deleted record"):
        update_effectivedated(
            db_per_file,
            ProductEd,
            ProductEd.gid == product_gid,
            new_values={"name": "Effdt Helper Original"},
            effdt=delete_effdt + dt.timedelta(minutes=1),
            last_saved_by="deleted.test",
        )

    with pytest.raises(ValueError, match="Cannot delete and update at the same time"):
        update_effectivedated(
            db_per_file,
            ProductEd,
            ProductEd.gid == product_gid,
            new_values={"name": "should fail"},
            delete=True,
            effdt=delete_effdt,
            last_saved_by="delete.test",
        )

    with pytest.raises(Required, match="last_saved_by is a required argument"):
        update_effectivedated(
            db_per_file,
            ProductEd,
            ProductEd.gid == product_gid,
            effdt=delete_effdt + dt.timedelta(minutes=2),
        )

    duplicate_gid = str(uuid.uuid4())
    duplicate_effdt = helper_base_effdt + dt.timedelta(minutes=10)
    for idx in (1, 2):
        db_per_file.executesql(
            """
            INSERT INTO product_ed (gid, supplier_gid, method_gid, olid, name, available, effdt, prio)
                VALUES (%(gid)s, %(supplier_gid)s, %(method_gid)s, %(olid)s, %(name)s, %(available)s, %(effdt)s, %(prio)s);
            """,
            placeholders={
                "gid": duplicate_gid,
                "supplier_gid": supplier_gid,
                "method_gid": method_gid,
                "olid": f"effdt-helper-dup-{idx}",
                "name": f"Effdt Helper Duplicate {idx}",
                "available": "leverbaar",
                "effdt": duplicate_effdt,
                "prio": idx,
            },
        )
    db_per_file.commit()

    with pytest.raises(ValueError, match="Multiple rows"):
        update_effectivedated(
            db_per_file,
            ProductEd,
            ProductEd.gid == duplicate_gid,
            effdt=duplicate_effdt,
            last_saved_by="duplicate.test",
        )


@pytest.mark.parametrize(
    ("table", "MigrationCls"),
    [
        ("alpha_test", AlphaTestModelMigration),
        ("beta_test", BetaTestModelMigration),
    ],
)
def test_dynamic_ed_insert_populates_dynamic_model(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    table: str,
    MigrationCls: type[ViewMigrationManager],
) -> None:
    """Dynamic tables should use the same insert-to-model sync behavior via the shared helper."""
    assert migrated_db_per_file is None

    gid = str(uuid.uuid4())
    fixed_effdt = dt.datetime(2026, 1, 1, 12, 0, 0)

    _drop_dynamic_derived_objects(db_per_file, table)
    _drop_dynamic_ed_table(db_per_file, table)
    _create_dynamic_ed_table(db_per_file, table)

    with MigrationCls(db_per_file):
        "during this block you can do alters on _ed since _model is dropped at this point"

    rows_sql = db_per_file.executesql(
        """
        SELECT routine_name
        FROM information_schema.routines
        WHERE routine_schema = 'public'
          AND routine_name IN (%(get_active)s, %(apply_change)s, %(rebuild)s)
        ORDER BY routine_name;
        """,
        placeholders={
            "get_active": f"get_active_{table}",
            "apply_change": f"apply_change_{table}_model",
            "rebuild": f"rebuild_{table}_model",
        },
        as_dict=True,
    )
    trigger_rows_sql = db_per_file.executesql(
        """
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE event_object_schema = 'public'
          AND event_object_table = %(table_ed)s
          AND trigger_name = %(trigger_name)s;
        """,
        placeholders={
            "table_ed": f"{table}_ed",
            "trigger_name": f"{table}_model_update_trigger",
        },
        as_dict=True,
    )

    assert rows_sql == [
        {"routine_name": f"apply_change_{table}_model"},
        {"routine_name": f"get_active_{table}"},
        {"routine_name": f"rebuild_{table}_model"},
    ]
    assert trigger_rows_sql == [{"trigger_name": f"{table}_model_update_trigger"}]

    db_per_file.executesql(
        f"""
        INSERT INTO {table}_ed (gid, olid, name, effdt, prio)
            VALUES (%(gid)s, %(olid)s, %(name)s, %(effdt)s, %(prio)s);
        """,
        placeholders={
            "gid": gid,
            "olid": f"{table}-low",
            "name": f"{table} low",
            "effdt": fixed_effdt,
            "prio": 1,
        },
    )
    db_per_file.executesql(
        f"""
        INSERT INTO {table}_ed (gid, olid, name, effdt, prio)
            VALUES (%(gid)s, %(olid)s, %(name)s, %(effdt)s, %(prio)s);
        """,
        placeholders={
            "gid": gid,
            "olid": f"{table}-high",
            "name": f"{table} high",
            "effdt": fixed_effdt,
            "prio": 5,
        },
    )
    db_per_file.commit()

    rows_sql = db_per_file.executesql(
        f"""
        SELECT gid, olid, name, prio, effdt
        FROM {table}_model
        WHERE gid = %(gid)s;
        """,
        placeholders={"gid": gid},
        as_dict=True,
    )

    assert rows_sql == [
        {
            "gid": gid,
            "olid": f"{table}-high",
            "name": f"{table} high",
            "prio": 5,
            "effdt": fixed_effdt,
        }
    ]

    _drop_dynamic_derived_objects(db_per_file, table)
    _drop_dynamic_ed_table(db_per_file, table)

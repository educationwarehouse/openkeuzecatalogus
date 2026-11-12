"""Exercise the catalogue migrations against an actual pre-change schema."""

import uuid

import pytest
from edwh_migrate.migrate import define_ewh_implemented_features

from shared_code.infra.database import DatabaseContext
from shared_code.migrations.migration_support.catalog_search_settings import (
    DynamicFilterModelWithPrio_V1,
    DynamicSortModelWithPrio_V1,
)
from shared_code.migrations.migration_support.product import ProductModelWithPrio_V1
from shared_code.migrations.migrations import (
    add_package_catalog_configuration_20261103_001,
    add_product_family_name_20261103_002,
)


def test_catalog_migrations_preserve_product_data_and_filter_history(
    migrated_db: DatabaseContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrading clones settings, versions method filters and leaves old products empty."""
    db = migrated_db
    define_ewh_implemented_features(db, migrate=False)
    monkeypatch.setenv("CURRENT_MIGRATION", "add_product_family_name_20261103_002")

    # This test owns a freshly migrated database, independent of module-scoped fixtures.
    db.executesql("TRUNCATE dynamic_filter_ed, dynamic_filter_model, dynamic_sort_ed, dynamic_sort_model;")
    with ProductModelWithPrio_V1(db):
        db.executesql("ALTER TABLE product_ed DROP COLUMN product_family_name;")

    # Restore the original globally unique slug indexes before upgrading them again.
    filter_manager = DynamicFilterModelWithPrio_V1(db)
    filter_manager.down()
    filter_manager.up()
    sort_manager = DynamicSortModelWithPrio_V1(db)
    sort_manager.down()
    sort_manager.up()

    supplier_gid = str(uuid.uuid4())
    method_gid = str(uuid.uuid4())
    method_filter_gid = str(uuid.uuid4())
    db.executesql(
        """
        INSERT INTO supplier_ed (gid, name, olid) VALUES (%(supplier)s, 'Migration Publisher', 'migration-publisher');
        INSERT INTO method_ed (gid, supplier_gid, olid, name)
        VALUES (%(method)s, %(supplier)s, 'migration-method', 'Derived Family');
        INSERT INTO product_ed (supplier_gid, method_gid, olid, name, composition, available)
        VALUES (%(supplier)s, %(method)s, 'migration-single', 'Single Product', 'single', 'leverbaar'),
               (%(supplier)s, %(method)s, 'migration-package', 'Package Product', 'package', 'leverbaar');
        INSERT INTO dynamic_filter_ed (
            gid, slug, label, filter_kind, field_name, match_mode, applies_to,
            handler_key, widget_kind, sort_order, prio, effdt
        ) VALUES (
            %(filter)s, 'mthd', 'Methodes', 'custom', 'method_gid', 'belongs', 'product',
            'method_lookup', 'select', 120, 25, '2020-01-01'
        );
        INSERT INTO dynamic_filter_ed (slug, label, filter_kind, field_name, applies_to, handler_key)
        VALUES ('cmp', 'Type', 'custom', 'composition', 'product', 'product_composition');
        INSERT INTO dynamic_sort_ed (slug, label, order_expression, applies_to, is_default)
        VALUES ('price', 'Adviesprijs', 'recommended_price', 'product', TRUE);
        """,
        placeholders={"supplier": supplier_gid, "method": method_gid, "filter": method_filter_gid},
    )
    db.commit()
    original_products = db.executesql(
        "SELECT * FROM product_ed WHERE olid IN ('migration-single', 'migration-package') ORDER BY id;", as_dict=True
    )

    monkeypatch.setenv("CURRENT_MIGRATION", "add_package_catalog_configuration_20261103_001")
    assert add_package_catalog_configuration_20261103_001(db) is True

    legacy_filters = db.executesql(
        "SELECT * FROM dynamic_filter_model WHERE slug = 'mthd' ORDER BY applies_to;", as_dict=True
    )
    assert {row["applies_to"] for row in legacy_filters} == {"product", "package"}
    assert len({row["gid"] for row in legacy_filters}) == 2
    assert all(row["handler_key"] == "method_lookup" for row in legacy_filters)
    assert db.executesql("SELECT slug FROM dynamic_filter_model WHERE applies_to = 'package' ORDER BY slug;") == [
        ("mthd",)
    ]
    assert db.executesql("SELECT applies_to, slug, order_expression FROM dynamic_sort_model ORDER BY applies_to;") == [
        ("package", "price", "recommended_price"),
        ("product", "price", "recommended_price"),
    ]

    monkeypatch.setenv("CURRENT_MIGRATION", "add_product_family_name_20261103_002")
    assert add_product_family_name_20261103_002(db) is True

    products = db.executesql(
        "SELECT * FROM product_ed WHERE olid IN ('migration-single', 'migration-package') ORDER BY id;", as_dict=True
    )
    assert len(products) == len(original_products)
    for original, product in zip(original_products, products, strict=True):
        assert product.pop("product_family_name") is None
        assert product == original
    assert db.executesql(
        "SELECT product_family_name FROM product_model "
        "WHERE olid IN ('migration-single', 'migration-package') ORDER BY id;"
    ) == [(None,), (None,)]

    for legacy in legacy_filters:
        history = db.executesql(
            "SELECT * FROM dynamic_filter_ed WHERE gid = %(gid)s ORDER BY id;",
            placeholders={"gid": legacy["gid"]},
            as_dict=True,
        )
        assert len(history) == 2
        assert history[0] == legacy
        current = db.executesql(
            "SELECT * FROM dynamic_filter_model WHERE gid = %(gid)s;",
            placeholders={"gid": legacy["gid"]},
            as_dict=True,
        )[0]
        assert current["id"] != legacy["id"]
        assert current["filter_kind"] == "dynamic"
        assert current["field_name"] == "product_family_name"
        assert current["match_mode"] == "belongs"
        assert current["handler_key"] is None
        for name in ("gid", "slug", "label", "applies_to", "is_active", "sort_order", "prio", "created_at"):
            assert current[name] == legacy[name]

    methods = db.executesql("SELECT gid, name FROM method_model WHERE olid = 'migration-method';")
    assert [(str(gid), name) for gid, name in methods] == [(method_gid, "Derived Family")]

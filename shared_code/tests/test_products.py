"""Tests for the product backend."""

import json
import typing as t
from pathlib import Path

from pytest import MonkeyPatch
from typedal import TypeDAL

from shared_code.data_model import DynamicFilter, DynamicSort, MethodEd, ProductEd, Supplier
from shared_code.services.applog import Applogger, DequeApplogger
from shared_code.services.applog.handler import process_applog_deque
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.products import ProductBackend


def _make_backend(auth: AuthAdapter, db: TypeDAL) -> ProductBackend:
    """Construct a product backend with endow injection."""
    return ProductBackend.with_injected(
        db=db,
        auth_adapter=auth,
    )
def test_product_backend_resolve_public_filters_uses_product_sort_options(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Public product filter resolution should expose configured product sort options."""
    assert migrated_db_per_file is None

    search_filter = dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=1,
    )
    product_sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    backend = _make_backend(AuthAdapter.for_service("products-public-filters"), db_per_file)
    resolved = backend.resolve_public_product_filters({search_filter.slug: [" algebra "]})

    filter_by_slug = {definition.slug: definition for definition in resolved.filters}

    assert resolved.entity_kind == "product"
    assert search_filter.slug in filter_by_slug
    assert filter_by_slug[search_filter.slug].current_value == "algebra"
    assert product_sort.slug in resolved.sort_options


def test_product_backend_list_public_products_excludes_removed_and_applies_sorting(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Public product listings should exclude removed rows and use configured sort order."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Product Supplier", email_domains=["product-public.example.test"])
    method = method_factory(
        supplier_gid=str(supplier.gid),
        olid="product-method-001",
        name="Product Method",
    )
    product_factory(
        supplier_gid=str(supplier.gid),
        method_gid=method.gid,
        olid="product-001",
        name="Beta Product",
    )
    product_factory(
        supplier_gid=str(supplier.gid),
        method_gid=method.gid,
        olid="product-002",
        name="Alpha Product",
    )
    product_factory(
        supplier_gid=str(supplier.gid),
        method_gid=method.gid,
        olid="product-003",
        name="Removed Product",
        available="verwijderd",
    )

    sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    backend = _make_backend(AuthAdapter.for_service("products-public-list"), db_per_file)
    rows = backend.list_public_products(sort=sort.slug, page=1, limit=10)

    assert [row.name for row in rows.data] == ["Alpha Product", "Beta Product"]
    assert rows.pagination["total_items"] == 2


def test_product_search_is_exported_to_catalog_search_report(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """A public product search should appear in the refreshed export report."""
    assert migrated_db_per_file is None
    deque_dir = tmp_path / "applog-deque"
    monkeypatch.setenv("APPLOG_FAKE", "0")
    monkeypatch.setenv("APPLOG_DEQUE_DIR", str(deque_dir))

    supplier = supplier_factory(name="Search Report Supplier", email_domains=["search-report.example.test"])
    method = method_factory(
        supplier_gid=str(supplier.gid),
        olid="search-report-method-001",
        name="Search Report Method",
    )
    product_factory(
        supplier_gid=str(supplier.gid),
        method_gid=method.gid,
        olid="search-report-product-001",
        name="Algebra Basis",
    )
    product_factory(
        supplier_gid=str(supplier.gid),
        method_gid=method.gid,
        olid="search-report-product-002",
        name="Algebra Plus",
    )
    search_filter = dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=1,
    )
    sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    backend = _make_backend(AuthAdapter.for_service("products-search-report"), db_per_file)
    filters = backend.resolve_public_product_filters({search_filter.slug: ["algebra"]})
    rows = backend.list_public_products(filters=filters, sort=sort.slug, page=1, limit=10)
    expected_ids = [row.id for row in rows]

    applog = backend.applog
    assert isinstance(applog, DequeApplogger)
    assert process_applog_deque(db_per_file, batch_size=1, applog=applog) > 0

    applog.refresh_catalog_search_report()

    entity_kind = "product"
    original_query = "algebra"

    report_rows = db_per_file.executesql(
        t"""
        SELECT result_ed_ids::text
        FROM catalog_search_report_v1
        WHERE {entity_kind = } AND {original_query = }
        """
    )

    assert [json.loads(row[0]) for row in report_rows] == [expected_ids]


def test_product_backend_list_my_products_returns_only_member_rows(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    auth_user_factory: t.Callable[..., t.Any],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Authenticated users should only see products for suppliers they belong to."""
    assert migrated_db_per_file is None

    visible_supplier = supplier_factory(name="Visible Product Supplier", email_domains=["visible-product.example.test"])
    hidden_supplier = supplier_factory(name="Hidden Product Supplier", email_domains=["hidden-product.example.test"])

    visible_method = method_factory(
        supplier_gid=str(visible_supplier.gid),
        olid="visible-product-method-001",
        name="Visible Product Method",
    )
    hidden_method = method_factory(
        supplier_gid=str(hidden_supplier.gid),
        olid="hidden-product-method-001",
        name="Hidden Product Method",
    )

    visible_product = product_factory(
        supplier_gid=str(visible_supplier.gid),
        method_gid=visible_method.gid,
        olid="visible-product-001",
        name="Visible Product",
    )
    hidden_product = product_factory(
        supplier_gid=str(hidden_supplier.gid),
        method_gid=hidden_method.gid,
        olid="hidden-product-001",
        name="Hidden Product",
    )

    user = auth_user_factory(prefix="product-member", domain="visible-product.example.test", roles=[str(visible_supplier.gid)])
    backend = _make_backend(auth_adapter_factory(user), db_per_file)

    rows = backend.list_my_products().collect()

    assert {str(row.gid) for row in rows} == {str(visible_product.gid)}
    assert str(hidden_product.gid) not in {str(row.gid) for row in rows}

"""Tests for the method backend."""

import json
import re
import typing as t
from pathlib import Path

from pytest import MonkeyPatch
from typedal import TypeDAL

from shared_code.data_model import DynamicFilter, DynamicSort, Method, MethodEd, ProductEd, Supplier
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.methods import MethodBackend
from shared_code.services.applog import DequeApplogger
from shared_code.services.applog.handler import process_applog_deque


def _make_backend(auth: AuthAdapter, db: TypeDAL) -> MethodBackend:
    """Construct a method backend with endow injection."""
    return MethodBackend.with_injected(
        db=db,
        auth_adapter=auth,
    )


def test_method_backend_resolve_public_filters_uses_method_sort_options(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Public method filter resolution should expose configured method sort options."""
    assert migrated_db_per_file is None

    search_filter = dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=1,
    )
    method_sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="method",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    backend = _make_backend(AuthAdapter.for_service("methods-public-filters"), db_per_file)
    resolved = backend.resolve_public_method_filters({search_filter.slug: [" rekenen "]})

    filter_by_slug = {definition.slug: definition for definition in resolved.filters}

    assert resolved.entity_kind == "method"
    assert search_filter.slug in filter_by_slug
    assert filter_by_slug[search_filter.slug].current_value == "rekenen"
    assert method_sort.slug in resolved.sort_options


def test_method_backend_list_public_methods_excludes_removed_and_applies_sorting(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Public method listings should exclude removed rows and use configured sort order."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Method Supplier", email_domains=["method-public.example.test"])
    beta_method = method_factory(supplier_gid=supplier.gid, olid="method-001", name="Beta Method")
    alpha_method = method_factory(supplier_gid=supplier.gid, olid="method-002", name="Alpha Method")
    method_factory(
        supplier_gid=supplier.gid,
        olid="method-003",
        name="Removed Method",
        available="verwijderd",
    )

    sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="method",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    product_factory(
        supplier_gid=supplier.gid,
        method_gid=beta_method.gid,
        olid="product-001",
        name="Beta Product",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=alpha_method.gid,
        olid="product-002",
        name="Alpha Product",
    )

    backend = _make_backend(AuthAdapter.for_service("methods-public-list"), db_per_file)
    rows = backend.list_public_methods(sort=sort.slug, page=1, limit=10)

    assert [row.name for row in rows.data] == ["Alpha Method", "Beta Method"]
    assert rows.pagination["total_items"] == 2


def test_public_method_product_filter_uses_joined_alias(db_per_file: TypeDAL) -> None:
    """Product availability must not introduce an unaliased product cross join."""
    query = MethodBackend._with_public_relations(Method.where(Method.available != "verwijderd").select(Method.gid))

    sql = query.to_sql()

    assert "CROSS JOIN" not in sql
    assert not re.search(r"FROM product_model(?:\s|,)", sql)
    assert re.search(r'"products_[^"]+"\."available" <> ', sql)


def test_method_search_is_exported_to_catalog_search_report(
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
    """A public method search should appear in the refreshed export report."""
    assert migrated_db_per_file is None
    deque_dir = tmp_path / "applog-deque"
    monkeypatch.setenv("APPLOG_FAKE", "0")
    monkeypatch.setenv("APPLOG_DEQUE_DIR", str(deque_dir))

    supplier = supplier_factory(
        name="Method Search Report Supplier", email_domains=["method-search-report.example.test"]
    )
    first_method = method_factory(
        supplier_gid=supplier.gid,
        olid="method-search-report-001",
        name="Rekenen Basis",
    )
    second_method = method_factory(
        supplier_gid=supplier.gid,
        olid="method-search-report-002",
        name="Rekenen Plus",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=first_method.gid,
        olid="method-search-report-product-001",
        name="Rekenen Basis Product",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=second_method.gid,
        olid="method-search-report-product-002",
        name="Rekenen Plus Product",
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
        applies_to="method",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    backend = _make_backend(AuthAdapter.for_service("methods-search-report"), db_per_file)
    filters = backend.resolve_public_method_filters({search_filter.slug: ["rekenen"]})
    rows = backend.list_public_methods(filters=filters, sort=sort.slug, page=1, limit=10)
    expected_ids = [row.id for row in rows]

    applog = backend.applog
    assert isinstance(applog, DequeApplogger)
    assert process_applog_deque(db_per_file, batch_size=1, applog=applog) == 1

    applog.refresh_catalog_search_report()

    entity_kind = "method"
    original_query = "rekenen"
    report_rows = db_per_file.executesql(
        t"""
        SELECT result_ed_ids::text
        FROM catalog_search_report_v1
        WHERE {entity_kind = } AND {original_query = }
        """
    )

    assert [json.loads(row[0]) for row in report_rows] == [expected_ids]


def test_method_backend_list_my_methods_returns_only_member_rows(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    auth_user_factory: t.Callable[..., t.Any],
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """Authenticated users should only see methods for suppliers they belong to."""
    assert migrated_db_per_file is None

    visible_supplier = supplier_factory(name="Visible Method Supplier", email_domains=["visible-method.example.test"])
    hidden_supplier = supplier_factory(name="Hidden Method Supplier", email_domains=["hidden-method.example.test"])

    visible_method = method_factory(
        supplier_gid=visible_supplier.gid,
        olid="visible-method-001",
        name="Visible Method",
    )
    hidden_method = method_factory(
        supplier_gid=hidden_supplier.gid,
        olid="hidden-method-001",
        name="Hidden Method",
    )

    user = auth_user_factory(prefix="method-member", domain="visible-method.example.test", roles=[visible_supplier.gid])
    backend = _make_backend(auth_adapter_factory(user), db_per_file)

    rows = backend.list_my_methods().collect()

    assert {row.gid for row in rows} == {visible_method.gid}
    assert hidden_method.gid not in {row.gid for row in rows}

    Method.where(Method.gid == visible_method.gid).first_or_fail().delete_record()
    db_per_file.commit()

    archived_rows = backend.list_my_methods(with_deleted=True).collect()

    assert {row.gid for row in archived_rows} == {visible_method.gid}
    assert {row.effstatus for row in archived_rows} == {True, False}


def test_method_backend_list_my_methods_with_deleted_returns_all_rows_for_admin(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    education_warehouse_admin_adapter: AuthAdapter,
) -> None:
    """Admins should see active and archived methods from every supplier."""
    assert migrated_db_per_file is None

    first_supplier = supplier_factory(name="Admin Method Supplier One", email_domains=["admin-method-one.example.test"])
    second_supplier = supplier_factory(
        name="Admin Method Supplier Two", email_domains=["admin-method-two.example.test"]
    )
    first_method = method_factory(
        supplier_gid=first_supplier.gid,
        olid="admin-method-001",
        name="Admin Method One",
    )
    second_method = method_factory(
        supplier_gid=second_supplier.gid,
        olid="admin-method-002",
        name="Admin Method Two",
    )

    Method.where(Method.gid == first_method.gid).first_or_fail().delete_record()
    db_per_file.commit()

    backend = _make_backend(education_warehouse_admin_adapter, db_per_file)
    rows = backend.list_my_methods(with_deleted=True).collect()
    row_gids = {row.gid for row in rows}

    assert {first_method.gid, second_method.gid}.issubset(row_gids)
    assert any(row.gid == first_method.gid and row.effstatus is False for row in rows)

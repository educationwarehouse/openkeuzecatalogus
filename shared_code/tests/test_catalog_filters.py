"""Tests for catalogue filter resolution and sorting."""

import typing as t

from typedal import TypeDAL

from shared_code.data_model import DynamicFilter, DynamicSort, MethodEd, Product, ProductEd, Supplier
from shared_code.modules.catalog_filters import CatalogFilters, any_value_matches


def test_any_value_matches_returns_none_or_matches_any_list_value(
    migrated_db_per_file: None,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """The overlap query is absent for no values and ORs all supplied values."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Overlap Supplier", email_domains=["overlap.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="overlap-method-001",
        name="Overlap Method",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="overlap-product-001",
        name="VMBO Product",
        levels=["vmbo"],
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="overlap-product-002",
        name="HAVO Product",
        levels=["havo"],
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="overlap-product-003",
        name="VWO Product",
        levels=["vwo"],
    )

    assert any_value_matches(Product.levels, []) is None

    query = any_value_matches(Product.levels, ["vmbo", "havo"])
    assert query is not None
    rows = Product.where(query).select(Product.olid, orderby=Product.olid)

    assert rows.column(Product.olid) == ["overlap-product-001", "overlap-product-002"]


def test_catalog_filters_resolve_product_filters_tracks_active_values(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Product filter resolution should keep the relevant definitions and values."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Catalog Supplier", email_domains=["catalog-filters.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="catalog-method-001",
        name="Catalog Method",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="catalog-product-001",
        name="Algebra Product",
        levels=["vmbo", "havo"],
    )

    search_filter = dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=1,
    )
    levels_filter = dynamic_filter_factory(
        slug="levels",
        label="Niveaus",
        filter_kind="dynamic",
        field_name="levels",
        applies_to="product",
        widget_kind="select",
        sort_order=2,
    )
    dynamic_filter_factory(
        slug="method-only",
        label="Method only",
        filter_kind="dynamic",
        field_name="available",
        applies_to="method",
        sort_order=3,
    )
    product_sort = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    filters = CatalogFilters.with_injected(db=db_per_file)
    sort_options = filters.sort_options("product")
    resolved = filters.resolve(
        "product",
        params={search_filter.slug: [" Algebra "], levels_filter.slug: ["vmbo", " vmbo ", "havo"]},
        option_builder=Product.where(Product.available != "verwijderd").select(Product.ALL),
        sort_options=sort_options,
    )

    filter_by_slug = {definition.slug: definition for definition in resolved.filters}
    active_by_slug = {definition.slug: value for definition, value in resolved.active_definitions}

    assert search_filter.slug in filter_by_slug
    assert levels_filter.slug in filter_by_slug
    assert filter_by_slug[search_filter.slug].current_value == "Algebra"
    assert filter_by_slug[levels_filter.slug].current_value == ["vmbo", "havo"]
    assert active_by_slug[search_filter.slug] == "Algebra"
    assert active_by_slug[levels_filter.slug] == ["vmbo", "havo"]
    assert resolved.active_filter_count >= 2
    assert product_sort.slug in resolved.sort_options


def test_catalog_filters_apply_combines_search_and_dynamic_filters(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
) -> None:
    """Applying resolved filters should narrow the result set to matching products."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Apply Supplier", email_domains=["apply-filters.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="apply-method-001",
        name="Apply Method",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="apply-product-001",
        name="Algebra VMBO",
        levels=["vmbo"],
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="apply-product-002",
        name="Algebra HAVO",
        levels=["havo"],
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="apply-product-003",
        name="Biology VMBO",
        levels=["vmbo"],
    )

    search_filter = dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=1,
    )
    levels_filter = dynamic_filter_factory(
        slug="levels",
        label="Niveaus",
        filter_kind="dynamic",
        field_name="levels",
        applies_to="product",
        widget_kind="select",
        sort_order=2,
    )

    filters = CatalogFilters.with_injected(db=db_per_file)
    resolved = filters.resolve(
        "product",
        params={search_filter.slug: ["Algebra"], levels_filter.slug: ["vmbo"]},
        option_builder=Product.where(Product.available != "verwijderd").select(Product.ALL),
    )

    rows = filters.apply(
        Product.where(Product.available != "verwijderd").select(Product.ALL),
        resolved,
    ).collect()

    assert [row.olid for row in rows] == ["apply-product-001"]


def test_catalog_filters_sort_options_skip_invalid_rows_and_fallback_to_default(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Sort option loading should ignore invalid rows and keep default fallback behavior."""
    assert migrated_db_per_file is None

    product_default = dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )
    product_secondary = dynamic_sort_factory(
        slug="edition-desc",
        label="Editie hoog-laag",
        applies_to="product",
        order_expression="~edition",
        sort_order=2,
    )
    dynamic_sort_factory(
        slug="invalid",
        label="Invalid",
        applies_to="product",
        order_expression="missing_field",
        sort_order=3,
    )
    method_default = dynamic_sort_factory(
        slug="method-name",
        label="Method Name",
        applies_to="method",
        order_expression="name",
        sort_order=4,
        is_default=True,
    )

    filters = CatalogFilters.with_injected(db=db_per_file)

    product_options = filters.sort_options("product")
    method_options = filters.sort_options("method")

    assert product_default.slug in product_options
    assert product_secondary.slug in product_options
    assert filters.default_sort_option("product").label == product_default.label
    assert filters.sort_option("product", "missing").label == product_default.label
    assert method_default.slug in method_options


def test_catalog_filters_default_sort_option_falls_back_to_id_without_options(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """An empty sort configuration should use the built-in stable fallback."""
    assert migrated_db_per_file is None

    filters = CatalogFilters.with_injected(db=db_per_file)

    fallback = filters.default_sort_option("product")

    assert fallback.label == "ID"
    assert fallback.is_default is True
    assert str(fallback.order) == str(Product.id)


def test_catalog_filters_skip_invalid_custom_filters_and_fallback_to_first_sort(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Invalid custom filter rows should be ignored and sort fallback should use first valid option."""
    assert migrated_db_per_file is None

    missing_field = dynamic_filter_factory(
        slug="missing-field",
        label="Missing field",
        filter_kind="custom",
        applies_to="product",
        sort_order=1,
        handler_key="has_value",
    )
    missing_handler = dynamic_filter_factory(
        slug="missing-handler",
        label="Missing handler",
        filter_kind="custom",
        applies_to="product",
        sort_order=2,
        field_name="isbn",
    )
    unknown_handler = dynamic_filter_factory(
        slug="unknown-handler",
        label="Unknown handler",
        filter_kind="custom",
        applies_to="product",
        sort_order=3,
        field_name="isbn",
        handler_key="not_a_real_handler",
    )
    valid_filter = dynamic_filter_factory(
        slug="has-isbn",
        label="Heeft ISBN",
        filter_kind="custom",
        applies_to="product",
        sort_order=4,
        field_name="isbn",
        handler_key="has_value",
    )
    first_sort = dynamic_sort_factory(
        slug="name-asc-no-default",
        label="Naam A-Z zonder default",
        applies_to="product",
        order_expression="name",
        sort_order=1,
    )
    second_sort = dynamic_sort_factory(
        slug="edition-desc-no-default",
        label="Editie hoog-laag zonder default",
        applies_to="product",
        order_expression="~edition",
        sort_order=2,
    )

    filters = CatalogFilters.with_injected(db=db_per_file)
    resolved = filters.resolve(
        "product",
        params={valid_filter.slug: ["1"]},
        option_builder=Product.where(Product.available != "verwijderd").select(Product.ALL),
    )
    resolved_slugs = {definition.slug for definition in resolved.filters}

    assert valid_filter.slug in resolved_slugs
    assert missing_field.slug not in resolved_slugs
    assert missing_handler.slug not in resolved_slugs
    assert unknown_handler.slug not in resolved_slugs
    assert resolved.active_filter_count == 1
    assert filters.default_sort_option("product").label == first_sort.label
    assert filters.sort_option("product", second_sort.slug).label == second_sort.label

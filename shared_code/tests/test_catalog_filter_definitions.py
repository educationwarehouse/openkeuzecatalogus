"""Focused coverage tests for sort validation, filter definitions, and vision search."""

import typing as t
import uuid
from types import SimpleNamespace

import pytest
from typedal import TypeDAL

from shared_code.data_model import DynamicSort, Method, MethodEd, Product, ProductEd, Supplier, Vision
from shared_code.data_model.validators.sort_expression import IS_SORT_EXPRESSION, parse_sort_expression
from shared_code.modules.catalog_filters.definitions import (
    BaseCatalogFilterDefinition,
    BooleanChoiceFilterDefinition,
    BudgetFilterDefinition,
    DynamicFieldFilterDefinition,
    HasValueFilterDefinition,
    InvalidCatalogFilterValue,
    MethodLookupFilterDefinition,
    ProductCompositionFilterDefinition,
    SearchFilterDefinition,
    SupplierFilterDefinition,
    as_flat_value_list,
    convert_attrs,
    flatten_filter_values,
    normalized_distinct_values,
    represent_filter_value,
    stringify_filter_value,
)
from shared_code.modules.catalog_filters.types import CatalogFilterContext, DynamicFilterMetadata, FilterOption


def _unique_slug(prefix: str) -> str:
    """Return a unique slug that fits the dynamic-sort table limit."""
    suffix = uuid.uuid4().hex[:8]
    trimmed_prefix = prefix[:31]
    return f"{trimmed_prefix}-{suffix}"


def _metadata(
    *,
    slug: str = "filter",
    label: str = "Filter",
    filter_kind: str = "dynamic",
    field_name: str | None = "name",
    match_mode: str = "contains",
    applies_to: str = "product",
    handler_key: str | None = None,
    widget_kind: str | None = None,
    sort_order: int = 1,
) -> DynamicFilterMetadata:
    """Build filter metadata with sensible defaults."""
    return DynamicFilterMetadata(
        slug=slug,
        label=label,
        filter_kind=filter_kind,
        field_name=field_name,
        match_mode=match_mode,
        applies_to=applies_to,
        handler_key=handler_key,
        widget_kind=widget_kind,
        sort_order=sort_order,
    )


class DummyFilterDefinition(BaseCatalogFilterDefinition):
    """Small concrete filter used to exercise base rendering behavior."""

    def parse(self) -> str | list[str] | bool | None:
        """Keep the dummy filter inactive by default."""
        return None

    def apply(self, builder: t.Any, active_value: str | list[str] | bool) -> t.Any:
        """Return the builder unchanged for rendering-only tests."""
        return builder

    def options(self) -> list[FilterOption]:
        """Expose a stable option set for rendering assertions."""
        return [
            FilterOption(value="one", label="One"),
            FilterOption(value="two", label="Two"),
        ]


def test_sort_expression_parser_and_validator_cover_edge_cases(
    migrated_db_per_file: None,
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Sort parsing and validation should handle blank, partial, and scoped expressions."""
    assert migrated_db_per_file is None

    assert parse_sort_expression(Product, "   ") == (None, {"other": ["no expression passed"]})
    assert parse_sort_expression(Product, "random") == ("random", {})
    assert parse_sort_expression(Product, " , ") == (None, {"other": ["no sortable fields parsed"]})
    assert parse_sort_expression(Product, "missing_field") == (None, {"fields": ["missing_field"]})

    parsed_order, issues = parse_sort_expression(Product, "name, ~edition")
    assert isinstance(parsed_order, tuple)
    assert len(parsed_order) == 2
    assert issues == {}

    validator = IS_SORT_EXPRESSION(error_message="bad sort")
    assert validator("   ") == (None, "bad sort")
    assert validator("composition") == ("composition", None)

    product_sort = dynamic_sort_factory(
        slug=_unique_slug("product-sort"),
        label="Product sort",
        applies_to="product",
        order_expression="name",
        sort_order=1,
    )
    method_sort = dynamic_sort_factory(
        slug=_unique_slug("method-sort"),
        label="Method sort",
        applies_to="method",
        order_expression="name",
        sort_order=2,
    )
    both_sort = dynamic_sort_factory(
        slug=_unique_slug("both-sort"),
        label="Both sort",
        applies_to="both",
        order_expression="name",
        sort_order=3,
    )

    assert validator("composition", record_id=product_sort.id) == ("composition", None)
    assert validator("composition", record_id=method_sort.id) == (None, "bad sort: onbekend veld composition")
    assert validator(" , ", record_id=both_sort.id) == (None, "bad sort: no sortable fields parsed")


def test_catalog_filter_helpers_and_base_rendering() -> None:
    """Helper functions and base rendering should normalize values consistently."""
    assert convert_attrs({"class": "btn", "_id": "existing"}) == {"_class": "btn", "_id": "existing"}
    assert list(flatten_filter_values([None, [" vmbo ", "havo"], "vwo"])) == [" vmbo ", "havo", "vwo"]
    assert stringify_filter_value(None) == ""
    assert stringify_filter_value("  algebra  ") == "algebra"
    assert as_flat_value_list(None) == []
    assert as_flat_value_list("single") == ["single"]
    assert as_flat_value_list(["one", 2, "two"]) == ["one", "two"]
    assert normalized_distinct_values([" vmbo ", "", "vmbo", " havo "]) == ["vmbo", "havo"]

    assert represent_filter_value(t.cast(t.Any, SimpleNamespace(type="list:string")), "  vmbo  ") == "vmbo"
    assert (
        represent_filter_value(
            t.cast(t.Any, SimpleNamespace(type="string", represent=lambda value, _row=None: f"two:{value}")),
            "abc",
        )
        == "two:abc"
    )
    assert (
        represent_filter_value(
            t.cast(t.Any, SimpleNamespace(type="string", represent=lambda value: f"one:{value}")),
            "abc",
        )
        == "one:abc"
    )
    assert (
        represent_filter_value(
            t.cast(t.Any, SimpleNamespace(type="string", represent=lambda _value, _row=None: None)),
            "  fallback  ",
        )
        == "fallback"
    )

    context = CatalogFilterContext(
        entity_kind="product",
        table=Product,
        params={},
        option_builder=Product.where(Product.id > 0).select(Product.ALL),
    )
    base_definition = BaseCatalogFilterDefinition(_metadata(slug="plain", label="Plain", field_name=None), context)

    assert base_definition.slug == "plain"
    assert base_definition.label == "Plain"
    assert base_definition.placeholder == ""
    assert base_definition.widget_kind == "select"
    assert base_definition.options() == []
    assert base_definition.filter_id() == "filter-plain"

    with pytest.raises(NotImplementedError):
        base_definition.parse()
    with pytest.raises(NotImplementedError):
        base_definition.apply(context.option_builder, "active")
    with pytest.raises(KeyError):
        _ = base_definition.field

    default_definition = DummyFilterDefinition(_metadata(slug="choice", widget_kind="checkbox"), context)
    default_definition.current_value = "two"
    default_html = default_definition.render().xml()
    assert 'class="form-select"' in default_html
    assert 'selected="selected"' in default_html

    single_select = DummyFilterDefinition(_metadata(slug="single"), context)
    single_select.current_value = "one"
    single_html = single_select.render().xml()
    assert 'data-widget="single-select"' in single_html
    assert 'type="radio"' in single_html
    assert 'checked="checked"' in single_html

    multi_select = DummyFilterDefinition(_metadata(slug="multi", widget_kind="multi-select"), context)
    multi_select.current_value = ["one", "two"]
    multi_html = multi_select.render().xml()
    assert 'data-widget="multi-select"' in multi_html
    assert 'type="checkbox"' in multi_html
    assert multi_html.count('checked="checked"') == 2


def test_search_and_dynamic_filter_definitions_apply_expected_queries(
    migrated_db_per_file: None,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Search and dynamic filters should parse and filter product builders correctly."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Definitions Supplier", email_domains=["definitions-filters.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="definitions-method-001",
        name="Definitions Method",
    )
    first_product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="definitions-product-001",
        name="Algebra VMBO",
        levels=["vmbo", "havo"],
    )
    assert first_product.follow_up_product != "None" # string non is an issue
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="definitions-product-002",
        name="Biology HAVO",
        levels=["havo"],
    )

    builder = Product.where(Product.available != "verwijderd").select(Product.ALL)

    search_context = CatalogFilterContext(
        entity_kind="product",
        table=Product,
        params={"q": [" Algebra "]},
        option_builder=builder,
    )
    search_definition = SearchFilterDefinition(_metadata(slug="q", filter_kind="search", widget_kind="search"), search_context)
    assert search_definition.widget_kind == "search"
    assert search_definition.placeholder == "Zoek op naam, OLID of ISBN"
    assert search_definition.parse() == "Algebra"
    assert (
        SearchFilterDefinition(
            _metadata(slug="q", filter_kind="search", applies_to="method", widget_kind="search"),
            CatalogFilterContext(entity_kind="method", table=Method, params={}, option_builder=Method.select(Method.ALL)),
        ).placeholder
        == "Zoek op naam of OLID"
    )
    search_rows = search_definition.apply(builder, "Algebra").collect()
    assert [row.olid for row in search_rows] == ["definitions-product-001"]

    passthrough_rows = SearchFilterDefinition(
        _metadata(slug="q", filter_kind="search", widget_kind="search"),
        CatalogFilterContext(entity_kind="product", table=t.cast(t.Any, object), params={}, option_builder=builder),
    ).apply(builder, "Algebra").collect()
    assert {row.olid for row in passthrough_rows} == {"definitions-product-001", "definitions-product-002"}

    scalar_context = CatalogFilterContext(
        entity_kind="product",
        table=Product,
        params={"available": [" leverbaar "]},
        option_builder=builder,
    )
    scalar_definition = DynamicFieldFilterDefinition(
        _metadata(slug="available", field_name="available", match_mode="belongs"),
        scalar_context,
    )
    assert scalar_definition.widget_kind == "select"
    assert scalar_definition.parse() == "leverbaar"
    assert len(scalar_definition.apply(builder, []).collect()) == 2

    list_context = CatalogFilterContext(
        entity_kind="product",
        table=Product,
        params={"levels": [" vmbo ", "havo", "vmbo"]},
        option_builder=builder,
    )
    list_definition = DynamicFieldFilterDefinition(
        _metadata(slug="levels", field_name="levels", match_mode="contains"),
        list_context,
    )
    assert list_definition.widget_kind == "multi-select"
    assert list_definition.parse() == ["vmbo", "havo"]
    level_rows = list_definition.apply(builder, ["vmbo"]).collect()
    assert [row.olid for row in level_rows] == ["definitions-product-001"]
    option_values = {(option.value, option.label) for option in list_definition.options()}
    assert option_values == {("havo", "havo"), ("vmbo", "vmbo")}


def test_custom_catalog_filter_definitions_filter_and_render_scope_lookups(
    migrated_db_per_file: None,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Custom filter definitions should expose present options and apply OR-style filtering."""
    assert migrated_db_per_file is None

    supplier_a = supplier_factory(name="Alpha Supplier", email_domains=["alpha-definitions.example.test"])
    supplier_b = supplier_factory(name="Beta Supplier", email_domains=["beta-definitions.example.test"])
    method_a = method_factory(
        supplier_gid=supplier_a.gid,
        olid="custom-method-001",
        name="Alpha Method",
        guide_price=12.0,
    )
    method_b = method_factory(
        supplier_gid=supplier_b.gid,
        olid="custom-method-002",
        name="Beta Method",
        guide_price=22.0,
    )

    product_factory(
        supplier_gid=supplier_a.gid,
        method_gid=method_a.gid,
        olid="custom-product-001",
        name="Budget Algebra",
        description="Has description",
        recommended_price=12.5,
        composition="single",
        tto=True,
    )
    product_factory(
        supplier_gid=supplier_b.gid,
        method_gid=method_b.gid,
        olid="custom-product-002",
        name="Package Biology",
        description="",
        recommended_price=22.5,
        composition="package",
        tto=False,
    )
    product_factory(
        supplier_gid=supplier_b.gid,
        method_gid=method_b.gid,
        olid="custom-product-003",
        name="Hidden Component",
        description=None,
        recommended_price=None,
        composition="component",
        tto=None,
    )

    builder = Product.where(Product.available != "verwijderd").select(Product.ALL)

    has_value = HasValueFilterDefinition(
        _metadata(slug="description", field_name="description", handler_key="has_value"),
        CatalogFilterContext(entity_kind="product", table=Product, params={"description": ["1"]}, option_builder=builder),
    )
    assert has_value.widget_kind == "checkbox"
    assert has_value.parse() is True
    assert [row.olid for row in has_value.apply(builder, True).collect()] == ["custom-product-001"]
    assert len(has_value.apply(builder, False).collect()) == 3

    boolean_choice = BooleanChoiceFilterDefinition(
        _metadata(slug="tto", field_name="tto", handler_key="boolean_choice"),
        CatalogFilterContext(entity_kind="product", table=Product, params={"tto": [" T "]}, option_builder=builder),
    )
    assert boolean_choice.parse() == "T"
    assert set(option.value for option in boolean_choice.options()) == {"T", "F"}
    assert [row.olid for row in boolean_choice.apply(builder, "T").collect()] == ["custom-product-001"]
    with pytest.raises(InvalidCatalogFilterValue):
        boolean_choice.apply(builder, "invalid").collect()

    with pytest.raises(InvalidCatalogFilterValue):
        bad_budget = BudgetFilterDefinition(
            _metadata(slug="bdgt", field_name="recommended_price", handler_key="budget_range"),
            CatalogFilterContext(
                entity_kind="product",
                table=Product,
                params={"bdgt": ["10-15", "abc-def", "10-15"]},
                option_builder=builder,
            ),
        )
        bad_budget.apply(builder, ["10-15", "abc-def", "20-30"])

    budget = BudgetFilterDefinition(
        _metadata(slug="recommended_price", field_name="recommended_price", handler_key="budget_range"),
        CatalogFilterContext(
            entity_kind="product",
            table=Product,
            params={"recommended_price": ["10-15", "20-30", "10-15"]},
            option_builder=builder,
        ),
    )
    assert budget.widget_kind == "multi-select"
    assert budget.parse() == ["10-15", "20-30"]
    assert [row.olid for row in budget.apply(builder, ["10-15", "20-30"]).collect()] == [
        "custom-product-001",
        "custom-product-002",
    ]
    assert len(budget.apply(builder, []).collect()) == 3
    assert budget.options()[0] == FilterOption(value="0.0-0.01", label="Onbekend")

    supplier_lookup = SupplierFilterDefinition(
        _metadata(slug="supplier_gid", field_name="supplier_gid", handler_key="supplier_lookup"),
        CatalogFilterContext(entity_kind="product", table=Product, params={"supplier_gid": [supplier_b.gid]}, option_builder=builder),
    )
    assert supplier_lookup.widget_kind == "multi-select"
    assert supplier_lookup.parse() == [supplier_b.gid]
    assert [row.label for row in supplier_lookup.options()] == ["Alpha Supplier", "Beta Supplier"]
    assert {row.olid for row in supplier_lookup.apply(builder, [supplier_b.gid]).collect()} == {
        "custom-product-002",
        "custom-product-003",
    }

    method_lookup = MethodLookupFilterDefinition(
        _metadata(slug="method_gid", field_name="method_gid", handler_key="method_lookup"),
        CatalogFilterContext(entity_kind="product", table=Product, params={"method_gid": [method_a.gid]}, option_builder=builder),
    )
    assert method_lookup.widget_kind == "multi-select"
    assert method_lookup.parse() == [method_a.gid]
    assert [row.label for row in method_lookup.options()] == ["Alpha Method", "Beta Method"]
    assert [row.olid for row in method_lookup.apply(builder, [method_a.gid]).collect()] == ["custom-product-001"]

    composition = ProductCompositionFilterDefinition(
        _metadata(slug="composition", field_name="composition", handler_key="product_composition"),
        CatalogFilterContext(entity_kind="product", table=Product, params={"composition": [" single ", "package"]}, option_builder=builder),
    )
    assert composition.widget_kind == "multi-select"
    assert composition.parse() == ["single", "package"]
    assert [option.value for option in composition.options()] == ["single", "package"]
    assert {row.olid for row in composition.apply(builder, ["single", "package"]).collect()} == {
        "custom-product-001",
        "custom-product-002",
    }
    assert len(composition.apply(builder, []).collect()) == 3


def test_vision_apply_search_matches_related_supplier_method_and_product_names(
    migrated_db_per_file: None,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., t.Any],
) -> None:
    """Vision search should also match names from related supplier, method, and product records."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Vision Supplier Name", email_domains=["vision-search.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="vision-method-001",
        name="Vision Method Name",
    )
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="vision-product-001",
        name="Vision Product Name",
    )

    vision_factory(
        olid=supplier.olid,
        onderwijskwaliteit="opbouw-leerdoelen",
        visie="Supplier linked vision",
    )
    vision_factory(
        olid=method.olid,
        onderwijskwaliteit="kwaliteit-effectiviteit",
        visie="Method linked vision",
    )
    vision_factory(
        olid=product.olid,
        onderwijskwaliteit="transparant-eerlijk",
        visie="Product linked vision",
    )

    assert len(Vision.apply_search("", Vision.select(Vision.ALL)).collect()) == 3
    assert [row.visie for row in Vision.apply_search("Supplier Name", Vision.select(Vision.ALL)).collect()] == [
        "Supplier linked vision"
    ]
    assert [row.visie for row in Vision.apply_search("Method Name", Vision.select(Vision.ALL)).collect()] == [
        "Method linked vision"
    ]
    assert [row.visie for row in Vision.apply_search("Product Name", Vision.select(Vision.ALL)).collect()] == [
        "Product linked vision"
    ]

"""Focused coverage tests for sort validation, filter definitions, and vision search."""

import typing as t
import uuid
from types import SimpleNamespace

import dill
import pytest
from typedal import TypeDAL

from shared_code.data_model import (
    CatalogEntityKind,
    DynamicSort,
    Method,
    MethodEd,
    Product,
    ProductEd,
    Supplier,
    Vision,
)
from shared_code.data_model.constants import get_themes
from shared_code.data_model.validators.sort_expression import (
    IS_SORT_EXPRESSION,
    parse_sort_expression,
    restore_sort_expression,
    sort_expression_table_name,
    stringify_sort_expression,
)
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
from shared_code.modules.catalog_filters.types import (
    CatalogFilterContext,
    CatalogSortOption,
    DynamicFilterMetadata,
    FilterOption,
    ResolvedCatalogFilters,
    find_filter_table,
)
from shared_code.util.types import CachableProtocol


@pytest.mark.parametrize("table", (Product, Method))
@pytest.mark.parametrize("shape", ("ascending", "descending", "tuple", "combined"))
def test_catalogue_sort_dill_round_trip(
    db_per_file: TypeDAL,
    table: type[Product] | type[Method],
    shape: str,
) -> None:
    """Cached sorts retain metadata and restore fields from the current models."""
    assert table._ensure_db() is db_per_file
    if shape == "ascending":
        order = table.name
    elif shape == "descending":
        order = ~table.name
    elif shape == "tuple":
        order = (table.name, ~table.id)
    else:
        order = table.name | ~table.id
    option = CatalogSortOption(label="Name", order=order, is_default=True, dynamic_sort_ed_id=42)

    cached = option.to_dillable()
    assert isinstance(option, CachableProtocol)
    assert isinstance(cached.order, str)
    assert cached._model == table._tablename
    assert option.order is order
    restored = CatalogSortOption.from_dillable(dill.loads(dill.dumps(cached)))

    assert stringify_sort_expression(restored.order) == stringify_sort_expression(order)
    assert restored.label == option.label
    assert restored.is_default is True
    assert restored.dynamic_sort_ed_id == 42
    assert restored._model == ""
    first = restored.order[0] if isinstance(restored.order, tuple) else restored.order
    assert first.db is table._ensure_db()


@pytest.mark.parametrize("order", ("random", "name", "~name"))
def test_catalogue_sort_dill_round_trip_without_bound_fields(order: str) -> None:
    """String sorts need no table binding during cache restoration."""
    option = CatalogSortOption(label="Sort", order=order)
    cached = option.to_dillable()
    restored = CatalogSortOption.from_dillable(dill.loads(dill.dumps(cached)))
    assert restored.order == order
    assert restored._model == ""


def test_catalogue_sort_serialization_rejects_unrestorable_orders(db_per_file: TypeDAL) -> None:
    """Fail explicitly for computed sorts, mixed tables and stale cache data."""
    assert Product._ensure_db() is db_per_file
    with pytest.raises(ValueError, match="only support fields"):
        stringify_sort_expression(Product.name.lower())
    with pytest.raises(ValueError, match="single table"):
        sort_expression_table_name((Product.name, Method.name))
    with pytest.raises(ValueError, match="Unknown cached catalogue sort table"):
        find_filter_table("missing_table")
    with pytest.raises(ValueError, match="Invalid cached catalogue sort expression"):
        restore_sort_expression(Product, "missing_field")


def _unique_slug(prefix: str) -> str:
    """Return a unique slug that fits the dynamic-sort table limit."""
    suffix = uuid.uuid4().hex[:8]
    trimmed_prefix = prefix[:31]
    return f"{trimmed_prefix}-{suffix}"


def _metadata(
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

    def build_options(self) -> list[FilterOption]:
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


@pytest.mark.parametrize("entity_kind", ["product", "method"])
@pytest.mark.parametrize("multiple", [False, True])
def test_capsule_dropdown_windows_large_option_sets_and_retains_selection(
    entity_kind: CatalogEntityKind, multiple: bool
) -> None:
    """Both filter pages keep an active option visible outside the first window."""
    context = CatalogFilterContext(
        entity_kind=entity_kind,
        table=Product,
        params={},
        option_builder=t.cast(t.Any, None),
    )
    definition = DummyFilterDefinition(_metadata(slug="choice"), context)
    definition.set_options([FilterOption(value=str(index), label=f"Option {index}") for index in range(4)])
    definition.current_value = ["3"] if multiple else "3"

    html = definition.render_capsule_dropdown(multiple=multiple, option_limit=2).xml()

    assert 'data-option-slug="choice"' in html
    assert f'data-option-kind="{entity_kind}"' in html
    assert 'data-option-limit="2"' in html
    assert html.count('name="choice"') == 3
    assert 'value="0"' in html
    assert 'value="1"' in html
    assert 'value="2"' not in html
    assert 'value="3"' in html
    assert html.count('checked="checked"') == 1

    unwindowed_html = definition.render_capsule_dropdown(multiple=multiple, option_limit=4).xml()
    assert "data-option-slug=" not in unwindowed_html
    assert unwindowed_html.count('name="choice"') == 4


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
    assert first_product.follow_up_product != "None"  # string non is an issue
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
    search_definition = SearchFilterDefinition(
        _metadata(slug="q", filter_kind="search", widget_kind="search"), search_context
    )
    assert search_definition.widget_kind == "search"
    assert search_definition.placeholder == "Zoek op naam, OLID of ISBN"
    assert search_definition.parse() == "Algebra"
    assert (
        SearchFilterDefinition(
            _metadata(slug="q", filter_kind="search", applies_to="method", widget_kind="search"),
            CatalogFilterContext(
                entity_kind="method", table=Method, params={}, option_builder=Method.select(Method.ALL)
            ),
        ).placeholder
        == "Zoek op naam of OLID"
    )
    search_rows = search_definition.apply(builder, "Algebra").collect()
    assert [row.olid for row in search_rows] == ["definitions-product-001"]

    passthrough_rows = (
        SearchFilterDefinition(
            _metadata(slug="q", filter_kind="search", widget_kind="search"),
            CatalogFilterContext(entity_kind="product", table=t.cast(t.Any, object), params={}, option_builder=builder),
        )
        .apply(builder, "Algebra")
        .collect()
    )
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
        CatalogFilterContext(
            entity_kind="product", table=Product, params={"description": ["1"]}, option_builder=builder
        ),
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
        CatalogFilterContext(
            entity_kind="product", table=Product, params={"supplier_gid": [supplier_b.gid]}, option_builder=builder
        ),
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
        CatalogFilterContext(
            entity_kind="product", table=Product, params={"method_gid": [method_a.gid]}, option_builder=builder
        ),
    )
    assert method_lookup.widget_kind == "multi-select"
    assert method_lookup.parse() == [method_a.gid]
    assert [row.label for row in method_lookup.options()] == ["Alpha Method", "Beta Method"]
    assert [row.olid for row in method_lookup.apply(builder, [method_a.gid]).collect()] == ["custom-product-001"]

    composition = ProductCompositionFilterDefinition(
        _metadata(slug="composition", field_name="composition", handler_key="product_composition"),
        CatalogFilterContext(
            entity_kind="product",
            table=Product,
            params={"composition": [" single ", "package"]},
            option_builder=builder,
        ),
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
    theme_gids = iter(get_themes())
    supplier_theme_gid = next(theme_gids)
    method_theme_gid = next(theme_gids)
    product_theme_gid = next(theme_gids)

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
        onderwijskwaliteit=supplier_theme_gid,
        visie="Supplier linked vision",
    )
    vision_factory(
        olid=method.olid,
        onderwijskwaliteit=method_theme_gid,
        visie="Method linked vision",
    )
    vision_factory(
        olid=product.olid,
        onderwijskwaliteit=product_theme_gid,
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


def test_options_are_built_once_and_reused_by_rendering() -> None:
    """Loading up front and rendering afterwards costs one set of queries, not two."""
    built: list[str] = []

    class Counting(DummyFilterDefinition):
        def build_options(self) -> list[FilterOption]:
            built.append(self.slug)
            return [FilterOption(value="a", label="A")]

    definition = Counting(_metadata(slug="levels"), t.cast(CatalogFilterContext, None))

    assert built == [], "resolving must not query"
    assert definition.options() == definition.options()
    assert built == ["levels"], "a second ask reuses the first result"


def test_load_options_moves_the_queries_out_of_rendering() -> None:
    """The handler forces the option queries so the template only formats them."""
    built: list[str] = []

    class Counting(DummyFilterDefinition):
        def build_options(self) -> list[FilterOption]:
            built.append(self.slug)
            return []

    definitions: list[BaseCatalogFilterDefinition] = [
        Counting(_metadata(slug=f"f{index}"), t.cast(CatalogFilterContext, None)) for index in range(3)
    ]
    resolved = ResolvedCatalogFilters(
        entity_kind="product",
        filters=definitions,
        active_definitions=[],
        active_filter_count=0,
    )

    assert resolved.load_options() is resolved, "chainable, so a handler resolves and loads in one expression"
    assert len(built) == 3, "every filter queried in the handler"

    built.clear()
    for definition in definitions:
        definition.options()  # what rendering does

    assert built == [], "rendering runs no queries of its own"


def test_option_page_searches_cached_options_and_preserves_active_selection() -> None:
    """Paging uses search offsets while returning the selected option once."""
    definition = DummyFilterDefinition(_metadata(slug="choice"), t.cast(CatalogFilterContext, None))
    definition.set_options(
        [
            FilterOption(value="alpha", label="Alpha"),
            FilterOption(value="beta", label="Beta"),
            FilterOption(value="gamma", label="Gamma"),
            FilterOption(value="delta", label="Delta"),
            FilterOption(value="selected", label="Epsilon"),
        ]
    )
    definition.current_value = ["selected"]
    resolved = ResolvedCatalogFilters(
        entity_kind="product",
        filters=[definition],
        active_definitions=[(definition, ["selected"])],
        active_filter_count=1,
    )

    first = resolved.option_page("choice", "  A  ", offset=0, limit=2)
    assert [option.value for option in first.options] == ["alpha", "beta"]
    assert [option.value for option in first.selected_options] == ["selected"]
    assert first.next_offset == 2
    assert first.has_more

    second = resolved.option_page("choice", "a", offset=first.next_offset, limit=2)
    assert [option.value for option in second.options] == ["gamma", "delta"]
    assert second.selected_options == []
    assert second.next_offset == 4
    assert not second.has_more

    selected_match = resolved.option_page("choice", "SELECTED", offset=0, limit=2)
    assert selected_match.options == []
    assert [option.value for option in selected_match.selected_options] == ["selected"]
    assert not selected_match.has_more

    with pytest.raises(KeyError, match="choice-missing"):
        resolved.option_page("choice-missing", "", offset=0, limit=2)


def test_options_survive_a_round_trip_through_plain_data() -> None:
    """A cached payload seeds the filters, so a hit renders without querying."""
    built: list[str] = []

    class Counting(DummyFilterDefinition):
        def build_options(self) -> list[FilterOption]:
            built.append(self.slug)
            return [FilterOption(value=f"{self.slug}-a", label="A")]

    def resolve() -> ResolvedCatalogFilters:
        definitions: list[BaseCatalogFilterDefinition] = [
            Counting(_metadata(slug=slug), t.cast(CatalogFilterContext, None)) for slug in ("levels", "subjects")
        ]
        return ResolvedCatalogFilters(
            entity_kind="product",
            filters=definitions,
            active_definitions=[],
            active_filter_count=0,
        )

    payload = resolve().load_options().options_payload()

    assert built == ["levels", "subjects"]
    assert payload == {"levels": [("levels-a", "A")], "subjects": [("subjects-a", "A")]}

    built.clear()
    restored = resolve().apply_options(payload)

    assert [option.value for option in restored.filters[0].options()] == ["levels-a"]
    assert built == [], "a seeded filter runs no query of its own"


def test_a_filter_missing_from_the_payload_still_loads_itself() -> None:
    """A filter added since the entry was written must not come back empty."""
    built: list[str] = []

    class Counting(DummyFilterDefinition):
        def build_options(self) -> list[FilterOption]:
            built.append(self.slug)
            return [FilterOption(value=f"{self.slug}-a", label="A")]

    definitions: list[BaseCatalogFilterDefinition] = [
        Counting(_metadata(slug=slug), t.cast(CatalogFilterContext, None)) for slug in ("levels", "language")
    ]
    resolved = ResolvedCatalogFilters(
        entity_kind="product",
        filters=definitions,
        active_definitions=[],
        active_filter_count=0,
    )

    resolved.apply_options({"levels": [("levels-a", "A")]})

    assert [option.value for option in resolved.filters[1].options()] == ["language-a"]
    assert built == ["language"], "only the filter the payload did not mention queried"

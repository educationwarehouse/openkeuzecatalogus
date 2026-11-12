"""Integration coverage for independently configured product and package tabs."""

import dataclasses as dc
import typing as t

import pytest

from shared_code.data_model import DynamicFilter, DynamicSort, MethodEd, Predicate, ProductEd, Supplier, TaggedEd
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.products import ProductBackend
from shared_code.services.caching import MemoryCacheService


@dc.dataclass
class CatalogScenario:
    """A mixed catalogue with separate configuration under the same request keys."""

    backend: ProductBackend
    family_slug: str
    composition_slug: str
    sort_slug: str
    package_filter: DynamicFilter


@pytest.fixture()
def catalog_scenario(
    db_per_file: DatabaseContext,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> CatalogScenario:
    """Seed visible, removed and component products with overlapping family names."""
    supplier = supplier_factory(name="Mixed Catalogue", email_domains=["mixed-catalog.example.test"])
    method = method_factory(supplier_gid=supplier.gid, olid="mixed-method", name="Derived Method")
    products: list[dict[str, t.Any]] = [
        {"olid": "single-a", "composition": "single", "product_family_name": "Alpha"},
        {"olid": "single-a2", "composition": "single", "product_family_name": "Alpha"},
        {"olid": "single-extended", "composition": "single", "product_family_name": "Alpha Extra"},
        {"olid": "single-b", "composition": "single", "product_family_name": "Beta"},
        {"olid": "single-null", "composition": "single", "product_family_name": None},
        {"olid": "single-blank", "composition": "single", "product_family_name": ""},
        {"olid": "package-a", "composition": "package", "product_family_name": "Alpha"},
        {"olid": "package-b", "composition": "package", "product_family_name": "Package Only"},
        {"olid": "component", "composition": "component", "product_family_name": "Component Only"},
        {
            "olid": "removed-single",
            "composition": "single",
            "product_family_name": "Removed Only",
            "available": "verwijderd",
        },
        {
            "olid": "removed-package",
            "composition": "package",
            "product_family_name": "Removed Package",
            "available": "verwijderd",
        },
    ]
    for values in products:
        product_factory(supplier_gid=supplier.gid, method_gid=method.gid, name=values["olid"], **values)

    family = dynamic_filter_factory(
        slug="family",
        label="Product families",
        filter_kind="dynamic",
        field_name="product_family_name",
        match_mode="belongs",
        applies_to="product",
        widget_kind="select",
        sort_order=1,
    )
    package_family = dynamic_filter_factory(
        slug=family.slug,
        unique_slug=False,
        label="Package families",
        filter_kind="dynamic",
        field_name="product_family_name",
        match_mode="belongs",
        applies_to="package",
        widget_kind="select",
        sort_order=1,
    )
    composition = dynamic_filter_factory(
        slug="composition",
        label="Type",
        filter_kind="custom",
        field_name="composition",
        handler_key="product_composition",
        applies_to="both",
        sort_order=2,
    )
    dynamic_filter_factory(
        slug=composition.slug,
        unique_slug=False,
        label="Type",
        filter_kind="custom",
        field_name="composition",
        handler_key="product_composition",
        applies_to="package",
        sort_order=2,
    )
    sort = dynamic_sort_factory(
        slug="alphabetical",
        label="Products ascending",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )
    dynamic_sort_factory(
        slug=sort.slug,
        unique_slug=False,
        label="Packages descending",
        applies_to="package",
        order_expression="~name",
        sort_order=1,
        is_default=True,
    )
    caching = MemoryCacheService.with_injected(db=db_per_file)
    backend = ProductBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("mixed-catalogue"), caching=caching
    )
    return CatalogScenario(backend, family.slug, composition.slug, sort.slug, package_family)


@pytest.mark.parametrize(
    ("catalog_kind", "expected_olids", "expected_families"),
    [
        (
            "product",
            {"single-a", "single-a2", "single-extended", "single-b", "single-null", "single-blank"},
            ["Alpha", "Alpha Extra", "Beta"],
        ),
        ("package", {"package-a", "package-b"}, ["Alpha", "Package Only"]),
    ],
)
def test_catalog_tabs_restrict_results_and_options_even_with_a_legacy_type_parameter(
    catalog_scenario: CatalogScenario,
    catalog_kind: t.Literal["product", "package"],
    expected_olids: set[str],
    expected_families: list[str],
) -> None:
    """Request parameters cannot reveal other compositions or their filter options."""
    scenario = catalog_scenario
    filters = scenario.backend.resolve_public_product_filters(
        params={scenario.composition_slug: ["single", "package", "component"], "composition": "component"},
        catalog_kind=catalog_kind,
    )
    definitions = {definition.slug: definition for definition in filters.filters}
    rows = scenario.backend.list_public_products(
        filters=filters, sort=scenario.sort_slug, page=1, limit=50, catalog_kind=catalog_kind
    )

    assert scenario.composition_slug not in definitions
    assert filters.active_filter_count == 0
    assert [option.value for option in definitions[scenario.family_slug].options()] == expected_families
    assert {row.olid for row in rows} == expected_olids
    assert rows.pagination["total_items"] == len(expected_olids)
    assert [row.name for row in rows] == sorted(expected_olids, reverse=catalog_kind == "package")


@pytest.mark.parametrize(
    ("catalog_kind", "other_family", "expected_olids"),
    [
        ("product", "Beta", {"single-a", "single-a2", "single-b"}),
        ("package", "Package Only", {"package-a", "package-b"}),
    ],
)
def test_family_filter_matches_exact_names_and_combines_selections_with_or(
    catalog_scenario: CatalogScenario,
    catalog_kind: t.Literal["product", "package"],
    other_family: str,
    expected_olids: set[str],
) -> None:
    """Selecting Alpha excludes Alpha Extra, null names and the derived method name."""
    scenario = catalog_scenario
    filters = scenario.backend.resolve_public_product_filters(
        params={scenario.family_slug: [" Alpha ", "Alpha", other_family]}, catalog_kind=catalog_kind
    )
    rows = scenario.backend.list_public_products(
        filters=filters, sort=scenario.sort_slug, page=1, limit=50, catalog_kind=catalog_kind
    )

    assert filters.active_filter_count == 1
    assert {row.olid for row in rows} == expected_olids


def test_cached_filter_options_and_configuration_stay_separate_for_each_scope(
    catalog_scenario: CatalogScenario,
) -> None:
    """Alternating tabs and recommendations never reuses another scope's options."""
    scenario = catalog_scenario
    for _ in range(2):
        products = scenario.backend.resolve_public_product_filters(catalog_kind="product")
        packages = scenario.backend.resolve_public_product_filters(catalog_kind="package")
        recommendations = scenario.backend.resolve_public_product_filters()
        product_filters = {definition.slug: definition for definition in products.filters}
        package_filters = {definition.slug: definition for definition in packages.filters}
        recommendation_filters = {definition.slug: definition for definition in recommendations.filters}

        assert product_filters[scenario.family_slug].label == "Product families"
        assert package_filters[scenario.family_slug].label == "Package families"
        assert [option.value for option in product_filters[scenario.family_slug].options()] == [
            "Alpha",
            "Alpha Extra",
            "Beta",
        ]
        assert [option.value for option in package_filters[scenario.family_slug].options()] == ["Alpha", "Package Only"]
        assert [option.value for option in recommendation_filters[scenario.family_slug].options()] == [
            "Alpha",
            "Alpha Extra",
            "Beta",
            "Component Only",
            "Package Only",
        ]
        assert scenario.composition_slug in recommendation_filters
        assert products.sort_options[scenario.sort_slug].label == "Products ascending"
        assert packages.sort_options[scenario.sort_slug].label == "Packages descending"

    scenario.package_filter.update_record(label="Renamed package families")
    products = scenario.backend.resolve_public_product_filters(catalog_kind="product")
    packages = scenario.backend.resolve_public_product_filters(catalog_kind="package")

    assert next(item for item in products.filters if item.slug == scenario.family_slug).label == "Product families"
    assert (
        next(item for item in packages.filters if item.slug == scenario.family_slug).label == "Renamed package families"
    )


def _bundle(package: ProductEd, component: ProductEd) -> None:
    """Store one imported package membership."""
    TaggedEd.insert(
        subject_gid=package.gid,
        predicate=Predicate.BUNDLES.value,
        object_gid=component.gid,
        last_saved_by="pytest",
    )


def test_product_detail_lists_package_contents_and_parent_packages(
    db_per_file: DatabaseContext,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Packages show their public contents, and bundled products link back to every public package."""
    supplier = supplier_factory(name="Bundle supplier", email_domains=["bundle-detail.example.test"])
    method = method_factory(supplier_gid=supplier.gid, olid="bundle-method", name="Bundle method")

    def product(name: str, composition: str, available: str = "leverbaar") -> ProductEd:
        return product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"bundle-{name}",
            name=name,
            composition=composition,
            available=available,
        )

    outer = product("Outer package", "package")
    package = product("Package", "package")
    other_package = product("Other package", "package")
    workbook = product("Workbook", "component")
    answers = product("Answers", "component")
    removed = product("Removed component", "component", available="verwijderd")
    single = product("Single", "single")
    for parent, child in ((outer, package), (package, workbook), (package, answers), (package, removed)):
        _bundle(parent, child)
    db_per_file.commit()

    backend = ProductBackend.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("bundle-detail"),
        caching=MemoryCacheService.with_injected(db=db_per_file),
    )

    package_detail = backend.get_public_product_detail(package.gid)
    workbook_detail = backend.get_public_product_detail(workbook.gid)
    single_detail = backend.get_public_product_detail(single.gid)
    assert package_detail is not None and workbook_detail is not None and single_detail is not None

    assert [item["name"] for item in package_detail["package_components"]] == ["Answers", "Workbook"]
    assert [item["name"] for item in package_detail["parent_packages"]] == ["Outer package"]
    assert [item["name"] for item in workbook_detail["parent_packages"]] == ["Package"]
    assert workbook_detail["package_components"] == []
    assert single_detail["package_components"] == []
    assert single_detail["parent_packages"] == []
    assert {item["name"] for item in single_detail["same_method_products"]} >= {"Package", "Workbook"}

    _bundle(other_package, workbook)
    db_per_file.commit()
    backend.caching.invalidate_table("tagged")

    workbook_detail = backend.get_public_product_detail(workbook.gid)
    assert workbook_detail is not None
    assert [item["name"] for item in workbook_detail["parent_packages"]] == ["Other package", "Package"]

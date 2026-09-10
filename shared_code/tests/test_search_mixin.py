"""Integration tests for SearchMixin on Product and Method."""

import typing as t

import pytest
from typedal import TypeDAL

from shared_code.data_model import Method, Product, ProductEd, SearchRankWeight, Supplier, SupplierEd, MethodEd
from shared_code.data_model.mixins.search import basic_search_query
from shared_code.infra.database.tables import is_readonly_table


@pytest.fixture(scope="module")
def seeded_products(migrated_db_per_file: None, db_per_file: TypeDAL) -> str:
    """Seed product rows for SearchMixin tests."""
    assert migrated_db_per_file is None
    assert db_per_file

    demo_supplier = SupplierEd.insert(name="DemoSupplier", olid="supplier-demo-1")
    demo_method = MethodEd.insert(supplier_gid=demo_supplier.gid)

    ProductEd.insert(
        name="Algebra Basisboek",
        olid="product-search-001",
        available="leverbaar",
        method_gid=demo_method.gid,
        supplier_gid=demo_supplier.gid,
    )
    ProductEd.insert(
        name="Algebra Werkboek",
        olid="product-search-002",
        available="leverbaar",
        method_gid=demo_method.gid,
        supplier_gid=demo_supplier.gid,
    )
    ProductEd.insert(
        name="Biologie Basisboek",
        olid="product-search-003",
        available="leverbaar",
        method_gid=demo_method.gid,
        supplier_gid=demo_supplier.gid,
    )
    ProductEd.insert(
        name="Basisboek Algebra",
        olid="product-search-004",
        available="leverbaar",
        method_gid=demo_method.gid,
        supplier_gid=demo_supplier.gid,
    )
    db_per_file.commit()
    return str(demo_supplier.gid)


def test_search_mixin_matches_single_term(seeded_products: str) -> None:
    """Single-term search should match rows containing the term."""
    rows = Product.search(
        "algebra",
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    names = {row.name for row in rows}

    assert names == {"Algebra Basisboek", "Algebra Werkboek", "Basisboek Algebra"}


def test_basic_search_matches_string_fields_on_a_generic_table(seeded_products: str) -> None:
    """Generic-table search finds text in string fields without a SearchMixin."""
    rows = ProductEd.where(basic_search_query("algebra", ProductEd)).collect()

    assert {row.name for row in rows} == {
        "Algebra Basisboek",
        "Algebra Werkboek",
        "Basisboek Algebra",
    }


def test_basic_search_matches_uuid_custom_fields_on_a_generic_table(seeded_products: str) -> None:
    """Generic-table search supports readable UUID custom fields."""
    rows = ProductEd.where(basic_search_query(seeded_products, ProductEd)).collect()

    assert {str(row.supplier_gid) for row in rows} == {seeded_products}


def test_is_readonly_table_detects_generated_and_maintained_tables(
    migrated_db_per_file: None, db_per_file: TypeDAL
) -> None:
    """Generated tables and tables with rebuild functions are readonly."""
    assert migrated_db_per_file is None

    assert is_readonly_table(db_per_file, "product_model")
    assert is_readonly_table(db_per_file, "product")
    assert not is_readonly_table(db_per_file, "product_ed")


def test_search_mixin_requires_all_terms(seeded_products: str) -> None:
    """Multi-term search should require all terms to match."""
    rows = Product.search(
        "algebra basisboek",
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    names = [row.name for row in rows]

    assert names == ["Algebra Basisboek", "Basisboek Algebra"]


def test_product_search_supports_quoted_and_negative_terms_and_safe_orderby(seeded_products: str) -> None:
    """Quoted phrases, excluded phrases, and order handling stay safe."""
    quoted_rows = Product.search(
        '"Algebra Basisboek"',
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    assert [row.name for row in quoted_rows] == ["Algebra Basisboek"]

    excluded_rows = Product.search(
        'algebra -"algebra basisboek"',
        builder=Product.where(Product.supplier_gid == seeded_products).select(orderby=Product.name),
    ).collect()
    assert [row.name for row in excluded_rows] == ["Algebra Werkboek", "Basisboek Algebra"]

    reverse_rows = Product.search(
        order="~name",
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    assert [row.name for row in reverse_rows] == [
        "Biologie Basisboek",
        "Basisboek Algebra",
        "Algebra Werkboek",
        "Algebra Basisboek",
    ]

    ranked_with_existing_order = Product.search(
        "basisboek",
        builder=Product.where(Product.supplier_gid == seeded_products).select(orderby=~Product.name),
    ).collect()
    # Previously the existing order took precedence; relevance now comes first.
    assert [row.name for row in ranked_with_existing_order] == [
        "Basisboek Algebra",
        "Biologie Basisboek",
        "Algebra Basisboek",
    ]

    unknown_order_rows = Product.search(
        order="~does_not_exist",
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    assert {row.name for row in unknown_order_rows} == {
        "Algebra Basisboek",
        "Algebra Werkboek",
        "Basisboek Algebra",
        "Biologie Basisboek",
    }


def test_product_search_matches_method_and_supplier_names_but_prefers_product_name(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Product search should include related method/supplier names after direct product-name matches."""
    assert migrated_db_per_file is None
    assert db_per_file

    supplier_direct = supplier_factory(name="Direct Supplier", email_domains=["direct-product-search.example.test"])
    supplier_secondary = supplier_factory(name="Target Supplier", email_domains=["secondary-product-search.example.test"])

    method_direct = method_factory(
        supplier_gid=str(supplier_direct.gid),
        olid="product-search-method-direct",
        name="General Method",
    )
    method_secondary = method_factory(
        supplier_gid=str(supplier_direct.gid),
        olid="product-search-method-secondary",
        name="Target Method",
    )
    method_supplier = method_factory(
        supplier_gid=str(supplier_secondary.gid),
        olid="product-search-method-supplier",
        name="Another Method",
    )

    product_factory(
        supplier_gid=str(supplier_direct.gid),
        method_gid=method_direct.gid,
        olid="product-search-direct",
        name="Zeta Target Product",
    )
    product_factory(
        supplier_gid=str(supplier_direct.gid),
        method_gid=method_secondary.gid,
        olid="product-search-method-hit",
        name="Alpha Product",
    )
    product_factory(
        supplier_gid=str(supplier_secondary.gid),
        method_gid=method_supplier.gid,
        olid="product-search-supplier-hit",
        name="Beta Product",
    )

    rows = Product.search(
        "target",
        builder=Product.where(Product.available == "leverbaar").select(orderby=Product.name),
    ).collect()

    assert [row.name for row in rows] == [
        "Zeta Target Product",
        # Supplier-name matches (70) rank above method-name matches (60).
        "Beta Product",
        "Alpha Product",
    ]


def test_product_search_score_overrides_change_result_order(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Unsaved preview scores should affect the relevance order without persisting them."""
    assert migrated_db_per_file is None
    assert db_per_file

    direct_supplier = supplier_factory(name="Preview Direct", email_domains=["preview-direct.example.test"])
    related_supplier = supplier_factory(name="Preview Target", email_domains=["preview-related.example.test"])
    direct_method = method_factory(supplier_gid=str(direct_supplier.gid), olid="preview-method-direct", name="General")
    related_method = method_factory(supplier_gid=str(related_supplier.gid), olid="preview-method-related", name="General")
    product_factory(
        supplier_gid=str(direct_supplier.gid),
        method_gid=direct_method.gid,
        olid="preview-product-direct",
        name="Target Product",
    )
    product_factory(
        supplier_gid=str(related_supplier.gid),
        method_gid=related_method.gid,
        olid="preview-product-related",
        name="Other Product",
    )

    supplier_rule = SearchRankWeight.where(
        (SearchRankWeight.entity_kind == "product") & (SearchRankWeight.label == "Leveranciersnaam")
    ).first()
    assert supplier_rule is not None

    rows = Product._apply_search(
        "target",
        Product.where(Product.available == "leverbaar").select(orderby=Product.name),
        score_overrides={supplier_rule.gid: {"contains": 600}},
    ).collect()

    assert [row.name for row in rows] == ["Other Product", "Target Product"]


def test_method_search_matches_supplier_names_but_prefers_method_name(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
) -> None:
    """Method search should include supplier-name matches after direct method-name matches."""
    assert migrated_db_per_file is None
    assert db_per_file

    supplier_direct = supplier_factory(name="General Method Supplier", email_domains=["direct-method-search.example.test"])
    supplier_secondary = supplier_factory(name="Target Method Supplier", email_domains=["secondary-method-search.example.test"])

    method_factory(
        supplier_gid=str(supplier_direct.gid),
        olid="method-search-direct",
        name="Zeta Target Method",
    )
    method_factory(
        supplier_gid=str(supplier_secondary.gid),
        olid="method-search-supplier-hit",
        name="Alpha Method",
    )

    rows = Method.search(
        "target",
        builder=Method.where(Method.available == "leverbaar").select(orderby=Method.name),
    ).collect()

    assert [row.name for row in rows] == [
        "Zeta Target Method",
        "Alpha Method",
    ]


def _random_sorted_page(supplier_gid: str, page: int) -> list[str]:
    """Return one page of the public-catalog query shape: filter, search, random sort, inner join."""
    builder = Product.where(Product.supplier_gid == supplier_gid).select(Product.ALL)
    builder = Product.apply_search("boek", builder)
    builder = Product.apply_orderby("random", builder)
    builder = builder.join("supplier", method="inner")

    return [row.name for row in builder.paginate(page=page, limit=2)]


def test_random_order_survives_distinct_and_pagination(seeded_products: str) -> None:
    """Random sorting must produce valid SQL under SELECT DISTINCT and not repeat rows across pages.

    Regression: `ORDER BY RANDOM()` made Postgres reject the paginated join query
    ("for SELECT DISTINCT, ORDER BY expressions must appear in select list").
    """
    first = _random_sorted_page(seeded_products, 1)
    second = _random_sorted_page(seeded_products, 2)

    assert len(first) == 2
    assert len(second) == 2
    assert not set(first) & set(second)
    assert set(first) | set(second) == {
        "Algebra Basisboek",
        "Algebra Werkboek",
        "Biologie Basisboek",
        "Basisboek Algebra",
    }
    # the daily seed keeps the shuffle stable within a run
    assert _random_sorted_page(seeded_products, 1) == first


def test_random_order_combines_with_search_ranking(seeded_products: str) -> None:
    """Applying the random order before the search keeps the relevance ranking in front."""
    rows = Product.search(
        "algebra",
        order="random",
        builder=Product.where(Product.supplier_gid == seeded_products).select(Product.ALL),
    ).collect()

    assert {row.name for row in rows} == {"Algebra Basisboek", "Algebra Werkboek", "Basisboek Algebra"}

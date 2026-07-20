"""Integration tests for SearchMixin on Product."""

import pytest
from typedal import TypeDAL

from shared_code.data_model import Product, Supplier, ProductEd, SupplierEd, MethodEd


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


def test_search_mixin_requires_all_terms(seeded_products: str) -> None:
    """Multi-term search should require all terms to match."""
    rows = Product.search(
        "algebra basisboek",
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    names = [row.name for row in rows]

    assert names == ["Algebra Basisboek", "Basisboek Algebra"]


def test_product_search_supports_quoted_terms_and_safe_orderby(seeded_products: str) -> None:
    """Quoted phrases, reverse order, preserved orderby, and bad order fields stay safe."""
    quoted_rows = Product.search(
        '"Algebra Basisboek"',
        builder=Product.where(Product.supplier_gid == seeded_products),
    ).collect()
    assert [row.name for row in quoted_rows] == ["Algebra Basisboek"]

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
    assert [row.name for row in ranked_with_existing_order] == [
        "Biologie Basisboek",
        "Basisboek Algebra",
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

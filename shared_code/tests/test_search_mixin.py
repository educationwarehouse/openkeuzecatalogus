"""Integration tests for SearchMixin on Product."""

import pytest
from typedal import TypeDAL

from shared_code.data_model import Product


@pytest.fixture(scope="module")
def seeded_products(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Seed product rows for SearchMixin tests."""
    assert migrated_db_per_file is None
    assert db_per_file

    Product.insert(
        name="Algebra Basisboek",
        olid="product-search-001",
        available="leverbaar",
    )
    Product.insert(
        name="Algebra Werkboek",
        olid="product-search-002",
        available="leverbaar",
    )
    Product.insert(
        name="Biologie Basisboek",
        olid="product-search-003",
        available="leverbaar",
    )
    db_per_file.commit()


def test_search_mixin_matches_single_term(seeded_products: None) -> None:
    """Single-term search should match rows containing the term."""
    assert seeded_products is None
    rows = Product.search("algebra").collect()
    names = {row.name for row in rows}

    assert names == {"Algebra Basisboek", "Algebra Werkboek"}


def test_search_mixin_requires_all_terms(seeded_products: None) -> None:
    """Multi-term search should require all terms to match."""
    assert seeded_products is None
    rows = Product.search("algebra basisboek").collect()
    names = [row.name for row in rows]

    assert names == ["Algebra Basisboek"]

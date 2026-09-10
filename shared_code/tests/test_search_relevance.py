"""Database-backed flow tests for search-relevance tuning."""

import typing as t

import pytest
from typedal import TypeDAL

from shared_code.data_model import Method, MethodEd, Product, ProductEd, SearchRankWeight, Supplier
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.search_relevance import SearchRelevance


def _relevance(db: TypeDAL) -> SearchRelevance:
    """Construct the relevance domain against the migrated test database."""
    return SearchRelevance.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("search-relevance-tests"),
    )


def _rule(entity_kind: str, key: str) -> SearchRankWeight:
    """Load one seeded ranking rule."""
    rule = SearchRankWeight.where(
        (SearchRankWeight.entity_kind == entity_kind) & (SearchRankWeight.key == key)
    ).first()
    assert rule is not None
    return rule


def test_search_rank_weight_table_format_uses_existing_fields(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """The generic table label should render a persisted ranking rule."""
    assert migrated_db_per_file is None
    assert db_per_file is not None

    rule = _rule("product", "name")
    table = SearchRankWeight._ensure_table_defined()

    assert table._format % rule == "product#name"


def test_product_relevance_preview_is_transient_then_saved_search_uses_the_score(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """A preview changes only the preview until the editor saves the score."""
    assert migrated_db_per_file is None

    direct_supplier = supplier_factory(name="Direct supplier", email_domains=["direct-relevance.example.test"])
    related_supplier = supplier_factory(name="Target supplier", email_domains=["related-relevance.example.test"])
    direct_method = method_factory(supplier_gid=str(direct_supplier.gid), olid="direct-method", name="General")
    related_method = method_factory(supplier_gid=str(related_supplier.gid), olid="related-method", name="General")
    product_factory(
        supplier_gid=str(direct_supplier.gid),
        method_gid=direct_method.gid,
        olid="direct-product",
        name="Target product",
    )
    product_factory(
        supplier_gid=str(related_supplier.gid),
        method_gid=related_method.gid,
        olid="related-product",
        name="Other product",
    )

    relevance = _relevance(db_per_file)
    supplier_rule = _rule("product", "supplier_name")
    values = {f"{supplier_rule.gid}-contains": "1300"}

    before_save = Product.search(
        "target", builder=Product.where(Product.available == "leverbaar").select(orderby=Product.name)
    ).collect()
    preview = relevance.preview("product", "target", values)

    assert [row.name for row in before_save] == ["Target product", "Other product"]
    assert [result["name"] for result in preview] == ["Other product", "Target product"]
    assert _rule("product", "supplier_name").contains == 50

    relevance.save("product", values)

    after_save = Product.search(
        "target", builder=Product.where(Product.available == "leverbaar").select(orderby=Product.name)
    ).collect()
    assert [row.name for row in after_save] == ["Other product", "Target product"]
    assert _rule("product", "supplier_name").contains == 1300


def test_product_and_method_relevance_settings_are_independent(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Saving a product rule neither changes method rules nor their editor values."""
    assert migrated_db_per_file is None

    relevance = _relevance(db_per_file)
    product_rule = _rule("product", "supplier_name")
    method_rule = _rule("method", "supplier_name")

    relevance.save("product", {f"{product_rule.gid}-exact": "900"})
    method_sections = relevance.sections("method")
    method_scores = {
        rule.key: rule.exact for section in method_sections for rule in section["rules"]
    }

    assert _rule("product", "supplier_name").exact == 900
    assert _rule("method", "supplier_name").exact == 70
    assert method_scores[method_rule.key] == 70


def test_relevance_save_rejects_invalid_scores_without_persisting_any_changes(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """A rejected form leaves all submitted score settings at their saved values."""
    assert migrated_db_per_file is None

    relevance = _relevance(db_per_file)
    name_rule = _rule("product", "name")
    supplier_rule = _rule("product", "supplier_name")
    saved_name_score = name_rule.exact
    saved_supplier_score = supplier_rule.exact

    with pytest.raises(ValueError):
        relevance.save(
            "product",
            {
                f"{name_rule.gid}-exact": "1500",
                f"{supplier_rule.gid}-exact": "5001",
            },
        )

    assert _rule("product", "name").exact == saved_name_score
    assert _rule("product", "supplier_name").exact == saved_supplier_score


def test_relevance_preview_handles_empty_queries_and_limits_results(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """The live preview has an empty state and returns only the first three matches."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Preview supplier", email_domains=["preview-relevance.example.test"])
    method = method_factory(supplier_gid=str(supplier.gid), olid="preview-method", name="Preview method")
    for number in range(4):
        product_factory(
            supplier_gid=str(supplier.gid),
            method_gid=method.gid,
            olid=f"preview-product-{number}",
            name=f"Preview product {number}",
        )

    relevance = _relevance(db_per_file)

    assert relevance.preview("product", "   ", {}) == []
    assert len(relevance.preview("product", "preview", {})) == 3

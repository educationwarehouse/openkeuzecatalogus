"""Tests for the recommendation contract and the overlap reason builder."""

import uuid

import pytest

from shared_code.data_model import MethodEd, Supplier, AuthUser
from shared_code.infra.database import DatabaseContext
from shared_code.modules.recommendations import (
    CatalogueOverlapRecommender,
    Recommender,
    Recommendation,
    RecommendationResult,
)
from shared_code.modules.decision_processes import DecisionProcessBackend

VESTIGING_CENTRUM_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"


def test_recommendation_dataclasses_are_stable() -> None:
    """Recommendation outputs are frozen values with optional ranking metadata."""
    recommendation = Recommendation(item="method", score=0.5, reasons=("Vakgebied: Rekenen",))
    result = RecommendationResult(methods=(recommendation,), products=())

    assert result.methods[0].item == "method"
    assert result.methods[0].score == 0.5
    assert result.products == ()


def test_catalogue_overlap_reasons_sorts_and_labels(
    db_per_file: DatabaseContext,
    supplier_factory,
    method_factory,
) -> None:
    """Matching subjects and levels are reported in stable, human-readable order."""
    supplier = supplier_factory(name="Recommend Supplier", email_domains=["recommend.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="METHOD-1",
        name="Methode",
        available="leverbaar",
    )
    method.update_record(subjects=["Rekenen"], levels=["Havo"])
    db_per_file.commit()

    assert CatalogueOverlapRecommender._reasons(method, ["Rekenen"], ["Havo"]) == (
        "Vakgebied: Rekenen",
        "Niveau: Havo",
    )


def test_recommender_from_env_builds_catalogue_overlap_implementation(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory,
) -> None:
    """The default recommender resolves to the catalogue-overlap strategy."""
    auth_adapter = auth_adapter_factory(admin_user)

    rec1 = Recommender.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    rec2 = CatalogueOverlapRecommender.with_injected(db=db_per_file, auth_adapter=auth_adapter)

    assert isinstance(rec1, CatalogueOverlapRecommender)
    assert isinstance(rec2, CatalogueOverlapRecommender)
    assert isinstance(rec2, Recommender)


def test_catalogue_overlap_recommend_returns_matching_methods_and_products(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory,
    supplier_factory,
    method_factory,
    product_factory,
) -> None:
    """The strategy recommends public methods and products matching the process fields."""
    auth_adapter = auth_adapter_factory(admin_user)
    backend = DecisionProcessBackend.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    team = backend.create_team(
        VESTIGING_CENTRUM_GID,
        "Recommendation Team",
        courses=["Rekenen"],
        levels=["Havo"],
    )
    process = backend.create_process(team.gid, "2026-2027")

    supplier = supplier_factory(name="Recommendation Supplier", email_domains=["recommendation.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="RECOMMEND-METHOD-1",
        name="Rekenmethode",
        available="leverbaar",
    )
    method.update_record(subjects=["Rekenen"], levels=["Havo"])
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="RECOMMEND-PRODUCT-1",
        name="Rekenproduct",
        levels=["Havo"],
        available="leverbaar",
    )
    product.update_record(subjects=["Rekenen"])
    db_per_file.commit()

    recommender = CatalogueOverlapRecommender.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    result = recommender.recommend(process.gid)

    assert {row.item.gid for row in result.methods} == {method.gid}
    assert {row.item.gid for row in result.products} == {product.gid}
    assert result.methods[0].reasons == ("Vakgebied: Rekenen", "Niveau: Havo")
    assert result.products[0].reasons == ("Vakgebied: Rekenen", "Niveau: Havo")


@pytest.mark.parametrize("broader_years", [None, [], ["vwo 5"]])
def test_catalogue_overlap_prioritises_products_matching_level_and_year(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory,
    supplier_factory,
    method_factory,
    product_factory,
    broader_years: list[str] | None,
) -> None:
    """Exact level-year matches precede broader matches, including missing year metadata."""
    auth_adapter = auth_adapter_factory(admin_user)
    backend = DecisionProcessBackend.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    team = backend.create_team(
        VESTIGING_CENTRUM_GID,
        "Level-year recommendation team",
        courses=["Rekenen"],
        levels=["Havo"],
        years=["havo 4"],
    )
    process = backend.create_process(team.gid, "2026-2027")

    supplier = supplier_factory(name="Level-year supplier", email_domains=["level-year.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="LEVEL-YEAR-METHOD-1",
        name="Rekenmethode",
        available="leverbaar",
    )
    broader_product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="LEVEL-YEAR-PRODUCT-1",
        name="A Brede match",
        levels=["Havo"],
    )
    exact_product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="LEVEL-YEAR-PRODUCT-2",
        name="Z Exacte match",
        levels=["Havo"],
    )
    broader_product.update_record(subjects=["Rekenen"], level_x_year=broader_years)
    exact_product.update_record(subjects=["Rekenen"], level_x_year=["havo 4"])
    db_per_file.commit()

    recommender = CatalogueOverlapRecommender.with_injected(db=db_per_file, auth_adapter=auth_adapter)
    result = recommender.recommend(process.gid)

    assert [recommendation.item.gid for recommendation in result.products] == [
        exact_product.gid,
        broader_product.gid,
    ]
    assert result.products[0].score == 1.0
    assert result.products[0].reasons == (
        "Vakgebied: Rekenen",
        "Niveau: Havo",
        "Niveau en leerjaar: havo 4",
    )
    assert result.products[1].score == 0.0
    assert result.product_total == 2


def test_recommendation_preview_limits_totals_sorting_and_empty_filters(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory,
    supplier_factory,
    method_factory,
    product_factory,
    dynamic_filter_factory,
    dynamic_sort_factory,
) -> None:
    """More than nine matches remain bounded while totals, sorts and filters stay accurate."""
    search_filter = dynamic_filter_factory(
        slug="q",
        label="Search",
        filter_kind="search",
        applies_to="product",
        widget_kind="search",
        sort_order=0,
    )
    prefix = f"Preview-{uuid.uuid4().hex}"
    supplier = supplier_factory(name=prefix, email_domains=["preview.example.test"])
    for index in range(12):
        method = method_factory(
            supplier_gid=supplier.gid, olid=f"{prefix}-method-{index}", name=f"{prefix} Method {index:02}"
        )
        method.update_record(subjects=[prefix], levels=["Havo"])
        product = product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"{prefix}-product-{index}",
            name=f"{prefix} Product {index:02}",
            levels=["Havo"],
        )
        product.update_record(subjects=[prefix], level_x_year=["havo 4"] if index < 3 else ["havo 5"])
    db_per_file.commit()

    adapter = auth_adapter_factory(admin_user)
    backend = DecisionProcessBackend.with_injected(db=db_per_file, auth_adapter=adapter)
    team = backend.create_team(VESTIGING_CENTRUM_GID, prefix, courses=[prefix], levels=["Havo"], years=["havo 4"])
    process = backend.create_process(team.gid, "2026-2027")
    recommender = CatalogueOverlapRecommender.with_injected(db=db_per_file, auth_adapter=adapter)
    result = recommender.recommend(process.gid)
    assert len(result.methods) == len(result.products) == 9
    assert result.method_total == result.product_total == 12
    assert [row.score for row in result.products[:3]] == [1.0, 1.0, 1.0]
    assert all(row.score == 0.0 for row in result.products[3:])

    sort = dynamic_sort_factory(
        slug="preview-desc", label="Descending", applies_to="product", order_expression="~name", sort_order=999
    )
    product_filters = recommender.products.resolve_public_product_filters({search_filter.slug: prefix})
    sorted_result = recommender.recommend(process.gid, product_filters=product_filters, sort=sort.slug)
    assert [row.item.name for row in sorted_result.products] == [
        f"{prefix} Product {index:02}" for index in range(11, 2, -1)
    ]
    assert sorted_result.product_total == 12

    product_filters = recommender.products.resolve_public_product_filters(
        {search_filter.slug: f'"{prefix} Product 11"'}
    )
    filtered = recommender.recommend(process.gid, product_filters=product_filters)
    assert filtered.product_total == 1
    assert [row.item.name for row in filtered.products] == [f"{prefix} Product 11"]
    empty = recommender.recommend(
        process.gid,
        product_filters=recommender.products.resolve_public_product_filters(
            {search_filter.slug: f"Absent{uuid.uuid4().hex}"}
        ),
    )
    assert empty.products == ()
    assert empty.product_total == 0

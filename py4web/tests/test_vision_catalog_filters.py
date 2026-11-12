"""Render regressions for the private recommendation filter form."""

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qs, urlsplit

import pytest
from apps.private.models.backend import PrivateBackend
from apps.private.models.vision import VisionTemplateContext
from apps.private.models.vision_catalog import vision_catalog_context
from common.models import db
from common.models.rendering import render_template

from py4web import request
from shared_code.data_model import (
    DecisionProcess,
    DecisionTeam,
    DecisionTeamEd,
    DynamicFilterEd,
    DynamicSortEd,
    MethodEd,
    ProductEd,
    SupplierEd,
)
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.catalog_filters import ResolvedCatalogFilters
from shared_code.services.caching import MemoryCacheService


class VisionCatalogueData(TypedDict):
    """Persisted process and catalogue data for recommendation controls."""

    backend: PrivateBackend
    context: VisionTemplateContext
    subject: str
    subject_slug: str
    level_slug: str
    search_slug: str
    sort_slug: str
    prefix: str


@pytest.fixture()
def vision_catalogue_data(admin_app_request_context: None) -> Iterator[VisionCatalogueData]:
    """Use the real database, filters and recommender with transaction-local catalogue rows."""
    request.app_name = "private"
    prefix = f"Vision-{uuid.uuid4().hex[:16]}"
    backend = PrivateBackend.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("pytest-vision-catalogue"),
        caching=MemoryCacheService.with_injected(db=db),
    )
    try:
        subject_slug = f"{prefix}-subjects"
        level_slug = f"{prefix}-levels"
        search_slug = f"{prefix}-search"
        sort_slug = f"{prefix}-descending"
        for slug, field in ((subject_slug, "subjects"), (level_slug, "levels")):
            DynamicFilterEd.insert(
                slug=slug,
                label=field,
                filter_kind="dynamic",
                field_name=field,
                match_mode="belongs",
                applies_to="both",
                widget_kind="select",
                is_active=True,
                sort_order=900,
            )
        DynamicFilterEd.insert(
            slug=search_slug,
            label="Search",
            filter_kind="search",
            applies_to="both",
            widget_kind="search",
            is_active=True,
            sort_order=901,
        )
        DynamicSortEd.insert(
            slug=sort_slug,
            label="Descending",
            applies_to="product",
            order_expression="~name",
            is_active=True,
            sort_order=900,
        )
        supplier = SupplierEd.insert(name=prefix, olid=f"{prefix}-supplier")
        method = MethodEd.insert(
            supplier_gid=supplier.gid,
            olid=f"{prefix}-method",
            name=f"{prefix} Method",
            available="leverbaar",
            subjects=[prefix],
            levels=["Havo"],
        )
        for index in range(12):
            ProductEd.insert(
                supplier_gid=supplier.gid,
                method_gid=method.gid,
                olid=f"{prefix}-product-{index}",
                name=f"{prefix} Product {index:02}",
                available="leverbaar",
                subjects=[prefix],
                levels=["Havo"],
                level_x_year=["havo 4"],
            )
        ProductEd.insert(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"{prefix}-other-level",
            name=f"{prefix} Other level",
            available="leverbaar",
            subjects=[prefix],
            levels=["Vwo"],
        )
        team_row = DecisionTeamEd.insert(
            location_gid="db1e5f11-b1d0-4ca2-b350-57e089fe159d",
            name=prefix,
            courses=[prefix],
            levels=["Havo"],
            years=["havo 4"],
        )
        team = DecisionTeam.where(DecisionTeam.gid == team_row.gid).collect().first()
        assert team is not None
        process = DecisionProcess.insert(team_gid=team.gid, schoolyear="2026-2027", start_date=dt.date(2026, 9, 1))
        context = VisionTemplateContext(
            dm_process=process,
            team=team,
            theme_vision=[],
            themes={},
            recommendations=backend.recommender.recommend(process.gid),
        )
        yield VisionCatalogueData(
            backend=backend,
            context=context,
            subject=prefix,
            prefix=prefix,
            subject_slug=subject_slug,
            level_slug=level_slug,
            search_slug=search_slug,
            sort_slug=sort_slug,
        )
    finally:
        db.rollback()


def test_recommendation_controls_lock_team_criteria_and_preserve_preview_totals(
    vision_catalogue_data: VisionCatalogueData,
) -> None:
    """URL overrides cannot broaden team criteria, and previews retain full result counts."""
    data = vision_catalogue_data
    context = vision_catalog_context(
        data["backend"],
        data["context"],
        {"kind": "product", data["subject_slug"]: ["unrelated"], data["level_slug"]: ["Vwo"], "sort": "invalid"},
    )
    assert context["active_kind"] == "product"
    assert context["selected_sort"] == ""
    assert {data["subject_slug"], data["level_slug"]} <= context["locked_filter_slugs"]
    assert context["method_count"] == 1
    assert context["product_count"] == 12
    methods, products = context["recommendation_groups"]
    assert not methods["has_more"]
    assert products["has_more"]
    assert len(products["visible_recommendations"]) == 9
    query = parse_qs(urlsplit(products["catalog_url"]).query)
    assert query[data["subject_slug"]] == [data["subject"].strip().casefold()]
    assert query[data["level_slug"]] == ["Havo"]
    assert "sort" not in query


@pytest.mark.parametrize(("search", "expected_count"), [("Product 11", 1), ("does-not-exist", 0)])
def test_recommendation_search_requeries_and_preserves_criteria_in_catalogue_links(
    vision_catalogue_data: VisionCatalogueData,
    search: str,
    expected_count: int,
) -> None:
    """Additional search filters produce fresh counts and correctly encoded full-catalogue links."""
    data = vision_catalogue_data
    # Match the full phrase so random prefix digits cannot satisfy a separate search term.
    term = f'"{data["prefix"]} {search}"'
    context = vision_catalog_context(
        data["backend"],
        data["context"],
        {"kind": "product", data["search_slug"]: term, "sort": data["sort_slug"]},
    )
    assert context["product_count"] == expected_count
    # Seeded method search also matches related product names.
    assert context["method_count"] == expected_count
    assert context["selected_sort"] == data["sort_slug"]
    methods = context["recommendation_groups"][0]
    expected_methods = []
    if expected_count:
        expected_methods = [f"{data['prefix']} Method"]
    assert [row.item.name for row in methods["visible_recommendations"]] == expected_methods
    products = context["recommendation_groups"][1]
    assert len(products["visible_recommendations"]) == expected_count
    query = parse_qs(urlsplit(products["catalog_url"]).query)
    assert query[data["search_slug"]] == [term]
    assert query[data["subject_slug"]] == [data["subject"].strip().casefold()]
    assert query[data["level_slug"]] == ["Havo"]
    assert query["sort"] == [data["sort_slug"]]


def test_recommendation_sort_and_reset_keep_independent_method_and_product_controls(
    vision_catalogue_data: VisionCatalogueData,
) -> None:
    """Product-only sorts reorder results without selecting an invalid method sort or losing criteria."""
    data = vision_catalogue_data
    sorted_context = vision_catalog_context(
        data["backend"],
        data["context"],
        {"kind": "method", "sort": data["sort_slug"]},
    )
    assert sorted_context["selected_sort"] == ""
    products = sorted_context["recommendation_groups"][1]
    assert [row.item.name for row in products["visible_recommendations"]] == [
        f"{data['prefix']} Product {index:02}" for index in range(11, 2, -1)
    ]
    reset_context = vision_catalog_context(data["backend"], data["context"], {})
    assert reset_context["active_kind"] == "method"
    assert reset_context["selected_sort"] == ""
    assert reset_context["method_count"] == 1
    assert reset_context["product_count"] == 12


def test_process_criteria_override_team_defaults_and_requested_filter_values(
    vision_catalogue_data: VisionCatalogueData,
) -> None:
    """Explicit process levels take precedence over both team defaults and URL parameters."""
    data = vision_catalogue_data
    process = data["context"]["dm_process"]
    process.update_record(levels=["Vwo"])
    data["context"]["recommendations"] = data["backend"].recommender.recommend(process.gid)

    context = vision_catalog_context(data["backend"], data["context"], {data["level_slug"]: ["Havo"]})

    assert context["active_kind"] == "product"
    assert context["method_count"] == 0
    assert context["product_count"] == 1
    products = context["recommendation_groups"][1]
    assert [row.item.name for row in products["visible_recommendations"]] == [f"{data['prefix']} Other level"]
    assert parse_qs(urlsplit(products["catalog_url"]).query)[data["level_slug"]] == ["Vwo"]


def test_private_recommendations_use_public_option_endpoint(admin_app_request_context: None) -> None:
    """Windowed filters must fetch root catalogue options from the private app."""
    request.app_name = "private"
    templates = Path(__file__).parents[1] / "apps/private/templates"
    html = render_template(
        "team/vision_catalog_filters.html",
        templates_path=templates,
        active_kind="product",
        selected_sort="",
        resolved_filters=ResolvedCatalogFilters(
            entity_kind="product", filters=[], active_definitions=[], active_filter_count=0
        ),
        locked_filter_slugs=set(),
        methods_url="/private/methods",
        products_url="/private/products",
        method_count=12,
        product_count=120,
    )
    assert 'data-option-url="/htmx/filter-options"' in html
    assert "Producten (120)" in html
    assert "Methodes (12)" in html

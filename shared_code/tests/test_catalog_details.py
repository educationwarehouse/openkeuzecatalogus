"""Tests for public catalogue detail payloads."""

import typing as t

import pytest
from endow import Injectable
from typedal import TypeDAL
from typedal.tables import TypedTable

from shared_code.data_model import Method, MethodEd, Product, ProductEd, Supplier, VisionEd
from shared_code.data_model.constants import get_themes
from shared_code.data_model.fields import is_public_readable_field
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend
from shared_code.services.applog import Applogger
from shared_code.tests.applog import RecordingApplogger


def _private_field_names(table: type[TypedTable]) -> set[str]:
    """Return model fields that must never be part of public payloads."""
    return {name for name in table.fields if not is_public_readable_field(table, name)}


def _vision_ids_for_single_theme(theme: str, vision_id: int) -> list[int | None]:
    """Return the logged IDs when only one theme has a resolved vision."""
    themes = get_themes()
    return [vision_id if current_theme == theme else None for current_theme in themes]


def _make_product_backend(db: TypeDAL, applog: Applogger | None = None) -> ProductBackend:
    """Construct a public product backend with an optional recording logger."""
    extra: dict[str, Injectable] = {}
    if applog:
        extra["applog"] = applog

    return ProductBackend.with_injected(
        db=db, auth_adapter=AuthAdapter.for_service("catalog-product-detail-test"), **extra
    )


def _make_method_backend(db: TypeDAL, applog: Applogger | None = None) -> MethodBackend:
    """Construct a public method backend with an optional recording logger."""
    extra: dict[str, Injectable] = {}
    if applog:
        extra["applog"] = applog

    return MethodBackend.with_injected(
        db=db, auth_adapter=AuthAdapter.for_service("catalog-method-detail-test"), **extra
    )


def test_product_detail_exposes_only_public_fields_and_prefers_method_visions(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., VisionEd],
) -> None:
    """Product details omit private fields and resolve method visions first."""
    assert migrated_db_per_file is None
    themes = get_themes()
    theme_gid = next(iter(themes))

    supplier = supplier_factory(name="Detail Supplier", email_domains=["product-detail.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="product-detail-method",
        name="Detail Method",
    )
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="product-detail-product",
        name="Detail Product",
        description="Public description",
        recommended_price=12.5,
    )
    vision_factory(
        olid=supplier.olid,
        onderwijskwaliteit=theme_gid,
        visie="Supplier vision",
    )
    vision_factory(
        olid=method.olid,
        onderwijskwaliteit=theme_gid,
        visie="Method vision",
    )

    detail = _make_product_backend(db_per_file).get_public_product_detail(product.gid)

    assert detail is not None
    assert detail["product"]["name"] == "Detail Product"
    assert detail["product"]["description"] == "Public description"
    assert detail["method"]["name"] == "Detail Method"
    assert detail["supplier"]["name"] == "Detail Supplier"
    for payload, table in ((detail["product"], Product), (detail["method"], Method), (detail["supplier"], Supplier)):
        assert not set(payload) & _private_field_names(table)
        assert all(is_public_readable_field(table, name) for name in payload)

    visions = {vision["theme"]: vision for vision in detail["visions"]}
    theme = themes[theme_gid]
    assert visions[theme] == {
        "theme": theme,
        "source": "Detail Method",
        "content": "Method vision",
        "properties": {},
    }


def test_method_detail_excludes_removed_products_and_falls_back_to_supplier_visions(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., VisionEd],
) -> None:
    """Method details only include public products and use supplier vision fallbacks."""
    assert migrated_db_per_file is None
    themes = get_themes()
    theme_gid = next(iter(themes))
    missing_theme_gid = next(gid for gid in themes if gid != theme_gid)

    supplier = supplier_factory(name="Method Detail Supplier", email_domains=["method-detail.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="method-detail-method",
        name="Method Detail",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="method-detail-public-product",
        name="Public related product",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="method-detail-removed-product",
        name="Removed related product",
        available="verwijderd",
    )
    vision_factory(
        olid=supplier.olid,
        onderwijskwaliteit=theme_gid,
        visie="Supplier fallback vision",
    )

    detail = _make_method_backend(db_per_file).get_public_method_detail(method.gid)

    assert detail is not None
    assert [product["name"] for product in detail["products"]] == ["Public related product"]
    visions = {vision["theme"]: vision for vision in detail["visions"]}
    theme = themes[theme_gid]
    missing_theme = themes[missing_theme_gid]
    assert visions[theme]["source"] == "Method Detail Supplier"
    assert visions[theme]["content"] == "Supplier fallback vision"
    assert visions[missing_theme] == {
        "theme": missing_theme,
        "source": "Method Detail Supplier",
        "content": "Nog niet gedeeld.",
        "properties": {},
    }


def test_public_detail_excludes_removed_records_without_logging(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Removed catalogue rows cannot be resolved or recorded as public details."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Removed Detail Supplier", email_domains=["removed-detail.example.test"])
    removed_method = method_factory(
        supplier_gid=supplier.gid,
        olid="removed-detail-method",
        name="Removed Method",
        available="verwijderd",
    )
    removed_product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=removed_method.gid,
        olid="removed-detail-product",
        name="Removed Product",
        available="verwijderd",
    )
    recorder = RecordingApplogger.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("catalog-removed-detail-test"),
    )

    assert _make_method_backend(db_per_file, applog=recorder).get_public_method_detail(removed_method.gid) is None
    assert _make_product_backend(db_per_file, applog=recorder).get_public_product_detail(removed_product.gid) is None
    assert recorder.fired_events == []


def test_product_and_method_details_log_resolved_vision_revision_ids(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., VisionEd],
) -> None:
    """Detail events record entity IDs and resolved vision revisions in theme order."""
    assert migrated_db_per_file is None
    theme_gid = next(iter(get_themes()))

    supplier = supplier_factory(name="Logged Detail Supplier", email_domains=["logged-detail.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="logged-detail-method",
        name="Logged Method",
    )
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="logged-detail-product",
        name="Logged Product",
    )
    vision = vision_factory(
        olid=method.olid,
        onderwijskwaliteit=theme_gid,
        visie="Logged vision",
    )
    recorder = RecordingApplogger.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("catalog-detail-event-test"),
    )

    assert _make_product_backend(db_per_file, applog=recorder).get_public_product_detail(product.gid) is not None
    assert _make_method_backend(db_per_file, applog=recorder).get_public_method_detail(method.gid) is not None

    product_event, method_event = recorder.fired_events
    expected_vision_ids = _vision_ids_for_single_theme(theme_gid, vision.id)
    assert product_event["details"] == {
        "entity_kind": "product",
        "requested_gid": product.gid,
        "result_ed_id": product.id,
        "vision_ed_ids": expected_vision_ids,
    }
    assert method_event["details"] == {
        "entity_kind": "method",
        "requested_gid": method.gid,
        "result_ed_id": method.id,
        "vision_ed_ids": expected_vision_ids,
    }


@pytest.mark.parametrize("entity_kind", ["product", "method"])
def test_visits_from_similar_materials_log_click_attribution_and_referrer(
    entity_kind: str,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Following a suggestion attributes the resolved detail view to its source."""
    supplier = supplier_factory(name="Suggestion click supplier", email_domains=["suggestion-click.example.test"])
    method = method_factory(supplier_gid=supplier.gid, olid="suggestion-click-method", name="Suggestion method")
    product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="suggestion-click-product",
        name="Suggestion product",
    )
    origin_method = method_factory(
        supplier_gid=supplier.gid, olid="suggestion-click-origin-method", name="Origin method"
    )
    origin_product = product_factory(
        supplier_gid=supplier.gid,
        method_gid=origin_method.gid,
        olid="suggestion-click-origin-product",
        name="Origin product",
    )
    recorder = RecordingApplogger.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("suggestion-click-tests")
    )
    if entity_kind == "product":
        source = product
        referer = f"https://openkeuzecatalogus.nl/product/{origin_product.gid}"
        detail = _make_product_backend(db_per_file, applog=recorder).get_public_product_detail(
            source.gid, referer=referer, from_similar=True
        )
    else:
        source = method
        referer = f"https://openkeuzecatalogus.nl/methode/{origin_method.gid}"
        detail = _make_method_backend(db_per_file, applog=recorder).get_public_method_detail(
            source.gid, referer=referer, from_similar=True
        )

    assert detail is not None
    assert len(recorder.fired_events) == 1
    event = recorder.fired_events[0]
    assert event["action"] == "catalog_detail"
    details = event["details"]
    assert details["entity_kind"] == entity_kind
    assert details["requested_gid"] == source.gid
    assert details["result_ed_id"] == source.id
    assert details["search_type"] == "similar"
    assert details["referer"] == referer

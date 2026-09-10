"""Tests for public catalogue detail payloads."""

import typing as t

from endow import Injectable
from typedal import TypeDAL
from typedal.tables import TypedTable

from shared_code.data_model import Method, MethodEd, Product, ProductEd, Supplier, VisionEd
from shared_code.data_model.constants import INTERNAL_FIELD_NAMES, THEMES
from shared_code.data_model.fields import is_public_readable_field
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend
from shared_code.services.applog import Applogger
from shared_code.tests.applog import RecordingApplogger


def _private_field_names(table: type[TypedTable]) -> set[str]:
    """Return model fields that must never be part of public payloads."""
    return {
        name
        for name in table.fields
        if name in INTERNAL_FIELD_NAMES or name.endswith("_gid") or not getattr(table[name], "readable", False)
    }


def _vision_ids_for_single_theme(theme: str, vision_id: int) -> list[int | None]:
    """Return the logged IDs when only one theme has a resolved vision."""
    return [vision_id if current_theme == theme else None for current_theme in THEMES]


def _make_product_backend(db: TypeDAL, applog: Applogger | None = None) -> ProductBackend:
    """Construct a public product backend with an optional recording logger."""
    extra: dict[str, Injectable] = {}
    if applog:
        extra["applog"] = applog

    return ProductBackend.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("catalog-product-detail-test"),
        **extra)


def _make_method_backend(db: TypeDAL, applog: Applogger | None = None) -> MethodBackend:
    """Construct a public method backend with an optional recording logger."""
    extra: dict[str, Injectable] = {}
    if applog:
        extra["applog"] = applog

    return MethodBackend.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("catalog-method-detail-test"),
        **extra)


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
        onderwijskwaliteit="kwaliteit-effectiviteit",
        visie="Supplier vision",
    )
    vision_factory(
        olid=method.olid,
        onderwijskwaliteit="kwaliteit-effectiviteit",
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
    assert visions[THEMES["kwaliteit-effectiviteit"]] == {
        "theme": THEMES["kwaliteit-effectiviteit"],
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
        onderwijskwaliteit="opbouw-leerdoelen",
        visie="Supplier fallback vision",
    )

    detail = _make_method_backend(db_per_file).get_public_method_detail(method.gid)

    assert detail is not None
    assert [product["name"] for product in detail["products"]] == ["Public related product"]
    visions = {vision["theme"]: vision for vision in detail["visions"]}
    assert visions[THEMES["opbouw-leerdoelen"]]["source"] == "Method Detail Supplier"
    assert visions[THEMES["opbouw-leerdoelen"]]["content"] == "Supplier fallback vision"
    assert visions[THEMES["evalueren-toetsen"]] == {
        "theme": THEMES["evalueren-toetsen"],
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

    assert _make_method_backend(db_per_file, recorder).get_public_method_detail(removed_method.gid) is None
    assert _make_product_backend(db_per_file, recorder).get_public_product_detail(removed_product.gid) is None
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
        onderwijskwaliteit="kwaliteit-effectiviteit",
        visie="Logged vision",
    )
    recorder = RecordingApplogger.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("catalog-detail-event-test"),
    )

    assert _make_product_backend(db_per_file, recorder).get_public_product_detail(product.gid) is not None
    assert _make_method_backend(db_per_file, recorder).get_public_method_detail(method.gid) is not None

    product_event, method_event = recorder.fired_events
    expected_vision_ids = _vision_ids_for_single_theme("kwaliteit-effectiviteit", vision.id)
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

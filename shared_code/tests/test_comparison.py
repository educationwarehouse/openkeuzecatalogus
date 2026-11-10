"""Tests for public comparison payload assembly."""

import typing as t

from typedal import TypeDAL

from shared_code.data_model import MethodEd, ProductEd, Supplier, VisionEd
from shared_code.data_model.constants import AnyDict, get_themes
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.comparison import ComparisonBackend
from shared_code.tests.applog import RecordingApplogger


def _make_backend(db: TypeDAL) -> ComparisonBackend:
    """Construct a comparison backend with its public catalogue dependencies."""
    return ComparisonBackend.with_injected(
        db=db,
        auth_adapter=AuthAdapter.for_service("comparison-public"),
    )


def test_product_comparison_keeps_url_order_and_uses_model_labels_and_representers(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Public product comparisons serialize readable labels and represented values."""
    assert migrated_db_per_file is None

    supplier = supplier_factory(name="Comparison Supplier", email_domains=["comparison.example.test"])
    method = method_factory(supplier_gid=supplier.gid, olid="comparison-method", name="Comparison Method")
    first = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="comparison-product-first",
        name="First Product",
        levels=["Leerjaar 1", "Leerjaar 2"],
    )
    second = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="comparison-product-second",
        name="Second Product",
    )
    removed = product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="comparison-product-removed",
        name="Removed Product",
        available="verwijderd",
    )

    page = _make_backend(db_per_file).load_public_comparison(
        "product",
        [second.gid, removed.gid, first.gid],
    )

    assert [record["name"] for record in page["records"]] == ["Second Product", "First Product"]
    assert page["missing_count"] == 1

    fields = {field["name"]: field for field in page["fields"]}
    assert fields["name"] == {
        "name": "name",
        "label": "Product Naam",
        "values": ["Second Product", "First Product"],
        "different": True,
    }
    assert fields["levels"] == {
        "name": "levels",
        "label": "Niveaus",
        "values": ["", "Leerjaar 1, Leerjaar 2"],
        "different": True,
    }
    assert not fields.keys() & {
        "id",
        "prio",
        "sync_gid",
        "effdt",
        "effstatus",
        "last_saved_by",
        "created_at",
        "updated_at",
        "supplier_gid",
        "method_gid",
    }


def test_method_comparison_prefers_method_visions_over_supplier_visions(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., VisionEd],
) -> None:
    """Method visions override supplier visions while supplier visions remain fallbacks."""
    assert migrated_db_per_file is None
    themes = get_themes()
    theme_gids = iter(themes)
    primary_theme_gid = next(theme_gids)
    fallback_theme_gid = next(theme_gids)
    missing_theme_gid = next(theme_gids)

    supplier = supplier_factory(name="Vision Supplier", email_domains=["vision-comparison.example.test"])
    supplier.update_record(olid="vision-comparison-supplier")
    db_per_file.commit()
    method = method_factory(
        supplier_gid=supplier.gid,
        olid="vision-comparison-method",
        name="Vision Method",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="vision-comparison-product",
        name="Vision Product",
    )
    vision_factory(
        olid=supplier.olid,
        onderwijskwaliteit=primary_theme_gid,
        visie="Supplier vision",
    )
    vision_factory(
        olid=method.olid,
        onderwijskwaliteit=primary_theme_gid,
        visie="Method vision",
    )
    vision_factory(
        olid=supplier.olid,
        onderwijskwaliteit=fallback_theme_gid,
        visie="Supplier fallback vision",
    )

    page = _make_backend(db_per_file).load_public_comparison("method", [method.gid])
    visions = {vision["theme"]: vision for vision in page["visions"]}

    assert visions[themes[primary_theme_gid]]["values"] == [
        {"content": "Method vision", "properties": "{}", "source": "Vision Method"}
    ]
    assert visions[themes[fallback_theme_gid]]["values"] == [
        {"content": "Supplier fallback vision", "properties": "{}", "source": "Vision Supplier"}
    ]
    assert visions[themes[missing_theme_gid]]["values"] == [
        {"content": "Nog niet gedeeld.", "properties": "{}", "source": "Vision Supplier"}
    ]


def test_method_comparison_logs_every_resolved_vision_revision(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    vision_factory: t.Callable[..., VisionEd],
) -> None:
    """Comparison events retain each record's resolved vision revision per theme."""
    assert migrated_db_per_file is None
    theme_gid = next(iter(get_themes()))

    supplier = supplier_factory(name="Event Supplier", email_domains=["event-comparison.example.test"])
    first_method = method_factory(
        supplier_gid=supplier.gid,
        olid="event-comparison-first-method",
        name="First Event Method",
    )
    second_method = method_factory(
        supplier_gid=supplier.gid,
        olid="event-comparison-second-method",
        name="Second Event Method",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=first_method.gid,
        olid="event-comparison-first-product",
        name="First Event Product",
    )
    product_factory(
        supplier_gid=supplier.gid,
        method_gid=second_method.gid,
        olid="event-comparison-second-product",
        name="Second Event Product",
    )
    first_vision = vision_factory(
        olid=first_method.olid,
        onderwijskwaliteit=theme_gid,
        visie="First method vision",
    )
    second_vision = vision_factory(
        olid=second_method.olid,
        onderwijskwaliteit=theme_gid,
        visie="Second method vision",
    )
    applog = RecordingApplogger.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("comparison-event-test"),
    )
    backend = ComparisonBackend.with_injected(
        db=db_per_file,
        auth_adapter=AuthAdapter.for_service("comparison-public"),
        applog=applog,
    )

    backend.load_public_comparison("method", [first_method.gid, second_method.gid])

    event = applog.fired_events[-1]
    details = t.cast(AnyDict, event["details"])
    assert details["vision_ed_ids"][theme_gid] == [first_vision.id, second_vision.id]

"""Database-backed tests for detail-page alternatives and global limiting."""

import typing as t
import uuid

import pytest
from typedal import PaginatedRows

from shared_code.data_model import AuthUser, CatalogusSetting, Method, MethodEd, Product, ProductEd, Supplier
from shared_code.data_model.fields import public_readable_values
from shared_code.generated.public_payloads import PublicMethod, PublicProduct
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.catalog_filters import CatalogEntityKind
from shared_code.modules.recommendations.similar_materials import SIMILAR_MATERIAL_LIMIT_KEY, SimilarMaterials
from shared_code.services.caching.memory import MemoryCacheService
from shared_code.tests.applog import RecordingApplogger


class SimilarCatalog(t.TypedDict):
    """Isolated catalogue fields and factories for one test."""

    supplier: Supplier
    other_supplier: Supplier
    subjects: list[str]
    levels: list[str]
    method: t.Callable[..., MethodEd]
    product: t.Callable[..., ProductEd]


@pytest.fixture()
def similar_materials(db_per_file: DatabaseContext) -> t.Iterator[SimilarMaterials]:
    """Use real database queries with a local cache and recording logger."""
    adapter = AuthAdapter.for_service("similar-materials-tests")
    recorder = RecordingApplogger.with_injected(db=db_per_file, auth_adapter=adapter)
    cache = MemoryCacheService.with_injected(db=db_per_file)
    recommendations = SimilarMaterials.with_injected(
        db=db_per_file, auth_adapter=adapter, applog=recorder, caching=cache
    )
    original_limit = recommendations.settings.get(SIMILAR_MATERIAL_LIMIT_KEY, default=9)
    recommendations.save_limit("9")
    try:
        yield recommendations
    finally:
        recommendations.settings.set(SIMILAR_MATERIAL_LIMIT_KEY, value=original_limit)
        cache.drop_all()


@pytest.fixture()
def similar_catalog(
    db_per_file: DatabaseContext,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> SimilarCatalog:
    """Create catalogue records through the existing effective-dated factories."""
    token = uuid.uuid4().hex
    supplier = supplier_factory(name="Similar supplier", email_domains=[f"similar-{token}.example.test"])
    other_supplier = supplier_factory(name="Other supplier", email_domains=[f"other-{token}.example.test"])
    subjects = [f"Subject {token} A", f"Subject {token} B"]
    levels = [f"Level {token} A", f"Level {token} B"]

    def create_method(
        name: str,
        subjects: list[str] | None = None,
        levels: list[str] | None = None,
        supplier: Supplier = supplier,
        available: str = "leverbaar",
        public_product_count: int = 1,
    ) -> MethodEd:
        method = method_factory(supplier_gid=supplier.gid, olid=uuid.uuid4().hex, name=name, available=available)
        method.update_record(
            subjects=subjects if subjects is not None else [f"Subject {token} A"],
            levels=levels if levels is not None else [f"Level {token} A"],
        )
        for number in range(public_product_count):
            product_factory(
                supplier_gid=supplier.gid,
                method_gid=method.gid,
                olid=uuid.uuid4().hex,
                name=f"{name} product {number}",
            )
        db_per_file.commit()
        return method

    def create_product(
        name: str,
        subjects: list[str] | None = None,
        levels: list[str] | None = None,
        supplier: Supplier = supplier,
        available: str = "leverbaar",
    ) -> ProductEd:
        method = method_factory(supplier_gid=supplier.gid, olid=uuid.uuid4().hex, name=f"{name} method")
        product = product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=uuid.uuid4().hex,
            name=name,
            levels=levels if levels is not None else [f"Level {token} A"],
            available=available,
        )
        product.update_record(subjects=subjects if subjects is not None else [f"Subject {token} A"])
        db_per_file.commit()
        return product

    return SimilarCatalog(
        supplier=supplier,
        other_supplier=other_supplier,
        subjects=subjects,
        levels=levels,
        method=create_method,
        product=create_product,
    )


def _alternatives(
    recommendations: SimilarMaterials, source: MethodEd | ProductEd
) -> PaginatedRows[Method] | PaginatedRows[Product]:
    """Pass the same public source payload used by the detail controllers."""
    if isinstance(source, ProductEd):
        payload: PublicProduct = public_readable_values(source, Product)
        return recommendations.for_product(payload)
    else:
        method_payload: PublicMethod = public_readable_values(source, Method)
        return recommendations.for_method(method_payload)


def _search_details(recommendations: SimilarMaterials) -> list[dict[str, t.Any]]:
    """Return only the search events recorded by the real recommendation flow."""
    recorder = t.cast(RecordingApplogger, recommendations.applog)
    return [
        t.cast(dict[str, t.Any], event["details"])
        for event in recorder.fired_events
        if event["action"] == "catalog_search"
    ]


def test_similar_products_require_subject_and_level_and_exclude_removed_and_current(
    similar_materials: SimilarMaterials, similar_catalog: SimilarCatalog
) -> None:
    """Supplier or one matching field alone cannot make a product relevant."""
    create = similar_catalog["product"]
    source = create("Source")
    relevant = create("Relevant", supplier=similar_catalog["other_supplier"])
    create("Wrong subject", subjects=["Unrelated subject"])
    create("Wrong level", levels=["Unrelated level"])
    create("Supplier only", subjects=["Unrelated subject"], levels=["Unrelated level"])
    create("Removed", available="verwijderd")

    rows = _alternatives(similar_materials, source)

    assert rows.column(Product.gid) == [relevant.gid]
    assert rows.pagination["total_items"] == 1
    assert rows[0].supplier.gid == similar_catalog["other_supplier"].gid
    assert rows[0].method.gid == relevant.method_gid


def test_similar_methods_require_subject_and_public_products_but_not_matching_level(
    similar_materials: SimilarMaterials,
    similar_catalog: SimilarCatalog,
    product_factory: t.Callable[..., ProductEd],
) -> None:
    """Methods match the subject across levels and need at least one public product."""
    create = similar_catalog["method"]
    source = create("Source")
    relevant = create("Relevant", levels=["Another level"], public_product_count=3)
    create("Wrong subject", subjects=["Unrelated subject"])
    create("Removed method", available="verwijderd")
    create("No products", public_product_count=0)
    removed_products = create("Only removed products", public_product_count=0)
    product_factory(
        supplier_gid=similar_catalog["supplier"].gid,
        method_gid=removed_products.gid,
        olid=uuid.uuid4().hex,
        name="Removed child",
        available="verwijderd",
    )

    rows = _alternatives(similar_materials, source)

    assert rows.column(Method.gid) == [relevant.gid]
    assert len(rows[0].products) == 3


@pytest.mark.parametrize("entity_kind", ["method", "product"])
def test_overlap_ranks_before_supplier_and_supplier_breaks_equal_overlap_ties(
    entity_kind: CatalogEntityKind, similar_materials: SimilarMaterials, similar_catalog: SimilarCatalog
) -> None:
    """An extra subject or level outranks supplier preference for both kinds."""
    create = similar_catalog[entity_kind]
    source = create("Source", subjects=similar_catalog["subjects"], levels=similar_catalog["levels"])
    same_supplier = create("Same supplier")
    other_supplier = create("Other supplier", supplier=similar_catalog["other_supplier"])
    extra_subject = create(
        "Extra subject", subjects=similar_catalog["subjects"], supplier=similar_catalog["other_supplier"]
    )
    extra_level = create("Extra level", levels=similar_catalog["levels"], supplier=similar_catalog["other_supplier"])

    rows = _alternatives(similar_materials, source)
    gids = rows.column("gid")

    assert set(gids[:2]) == {extra_subject.gid, extra_level.gid}
    assert gids[2:] == [same_supplier.gid, other_supplier.gid]
    details = _search_details(similar_materials)[0]
    assert details["search_type"] == "similar"
    assert details["entity_kind"] == entity_kind
    assert details["source_gid"] == source.gid
    assert details["result_count"] == 4
    assert details["result_ed_ids"] == rows.column("id")
    assert [result["score"] for result in details["result_scores"]] == [6, 6, 5, 4]
    assert details["dynamic_sort_ed_id"] is None
    assert details["active_filter_ed_ids"] == {}
    assert details["search_rank_weight_ed_ids"] == []


@pytest.mark.parametrize(
    ("entity_kind", "empty_field"), [("method", "subjects"), ("product", "subjects"), ("product", "levels")]
)
@pytest.mark.parametrize("missing_value", [[], [""]])
def test_missing_required_source_fields_return_no_suggestions(
    entity_kind: CatalogEntityKind,
    empty_field: str,
    missing_value: list[str],
    similar_materials: SimilarMaterials,
    similar_catalog: SimilarCatalog,
) -> None:
    """Missing source data does not broaden a search to unrelated materials."""
    create = similar_catalog[entity_kind]
    source = create("Source", **{empty_field: missing_value})
    create("Other item")

    rows = _alternatives(similar_materials, source)

    assert not rows
    details = _search_details(similar_materials)[0]
    assert details["result_count"] == 0
    assert details["result_ed_ids"] == []


@pytest.mark.parametrize("entity_kind", ["method", "product"])
def test_default_limit_is_nine_and_saved_changes_bypass_cached_limits(
    entity_kind: CatalogEntityKind, similar_materials: SimilarMaterials, similar_catalog: SimilarCatalog
) -> None:
    """Both detail kinds immediately use a globally saved limit, even with warm caches."""
    create = similar_catalog[entity_kind]
    source = create("Source")
    for number in range(10):
        create(f"Alternative {number}")

    initial = _alternatives(similar_materials, source)
    repeated = _alternatives(similar_materials, source)
    assert similar_materials.get_limit() == 9
    assert len(initial) == 9
    assert initial.pagination["total_items"] == 10
    assert repeated.column("gid") == initial.column("gid")

    similar_materials.save_limit("3")
    limited = _alternatives(similar_materials, source)
    limited_again = _alternatives(similar_materials, source)
    assert len(limited) == 3
    assert limited.pagination["total_items"] == 10
    assert limited.column("gid") == initial.column("gid")[:3]
    assert limited_again.column("gid") == limited.column("gid")

    fresh = SimilarMaterials.with_injected(
        db=similar_materials.settings.db,
        auth_adapter=AuthAdapter.for_service("another-similar-materials-visitor"),
        applog=similar_materials.applog,
        caching=similar_materials.caching,
    )
    assert fresh.get_limit() == 3
    assert len(_alternatives(fresh, source)) == 3

    similar_materials.save_limit("12")
    expanded = _alternatives(similar_materials, source)
    assert len(expanded) == 10
    assert expanded.pagination["total_items"] == 10
    details = _search_details(similar_materials)
    assert [event["suggestion_limit"] for event in details] == [9, 9, 3, 3, 3, 12]
    assert [event["cache_hit"] for event in details] == [False, True, False, True, True, False]
    assert [len(event["result_ed_ids"]) for event in details] == [9, 9, 3, 3, 3, 10]


@pytest.mark.parametrize("entity_kind", ["method", "product"])
def test_equal_rank_results_use_the_same_daily_shuffle_as_catalogue_search(
    entity_kind: CatalogEntityKind, similar_materials: SimilarMaterials, similar_catalog: SimilarCatalog
) -> None:
    """Uncached ties follow search's daily seeded ordering rather than insertion order."""
    create = similar_catalog[entity_kind]
    source = create("Source")
    alternatives = [create(f"Alternative {number}") for number in range(5)]
    gids = [alternative.gid for alternative in alternatives]
    if entity_kind == "product":
        expected = Product.apply_orderby("random", Product.where(Product.gid.belongs(gids))).column(Product.gid)
    else:
        expected = Method.apply_orderby("random", Method.where(Method.gid.belongs(gids))).column(Method.gid)

    first = _alternatives(similar_materials, source)
    similar_materials.caching.drop_all()
    second = _alternatives(similar_materials, source)

    assert first.column("gid") == expected
    assert second.column("gid") == expected
    assert [event["cache_hit"] for event in _search_details(similar_materials)] == [False, False]


@pytest.mark.parametrize("value", ["", " ", "0", "-1", "1.5", "true", "nine"])
def test_invalid_limit_submission_preserves_the_saved_value(value: str, similar_materials: SimilarMaterials) -> None:
    """Invalid input cannot overwrite an existing global limit."""
    similar_materials.save_limit("4")

    with pytest.raises(ValueError, match="minimaal 1"):
        similar_materials.save_limit(value)

    assert similar_materials.get_limit() == 4
    assert similar_materials.settings.get(SIMILAR_MATERIAL_LIMIT_KEY) == 4


@pytest.mark.parametrize("value", [True, False, 0, -1, 9.5, "9", None, [], {"value": 9}])
def test_invalid_stored_limits_fall_back_to_nine(value: object, similar_materials: SimilarMaterials) -> None:
    """A malformed JSON setting cannot create unbounded or invalid pagination."""
    similar_materials.settings.set(SIMILAR_MATERIAL_LIMIT_KEY, value=value)

    assert similar_materials.get_limit() == 9


def test_missing_limit_defaults_to_nine_and_can_be_saved_again(similar_materials: SimilarMaterials) -> None:
    """A missing configuration row uses the default and is recreated on save."""
    CatalogusSetting.where(CatalogusSetting.key == SIMILAR_MATERIAL_LIMIT_KEY).delete()
    similar_materials.settings.db.commit()

    assert similar_materials.get_limit() == 9

    similar_materials.save_limit("1")

    assert similar_materials.get_limit() == 1
    assert similar_materials.settings.get(SIMILAR_MATERIAL_LIMIT_KEY) == 1
    assert CatalogusSetting.where(CatalogusSetting.key == SIMILAR_MATERIAL_LIMIT_KEY).count() == 1


def test_normal_user_cannot_change_the_global_limit(
    db_per_file: DatabaseContext,
    normal_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    similar_materials: SimilarMaterials,
) -> None:
    """The limit editor remains protected when invoked through the domain directly."""
    visitor = SimilarMaterials.with_injected(
        db=db_per_file,
        auth_adapter=auth_adapter_factory(normal_user),
        applog=similar_materials.applog,
        caching=similar_materials.caching,
    )

    with pytest.raises(PermissionError):
        visitor.save_limit("2")

    assert visitor.get_limit() == 9
    assert similar_materials.get_limit() == 9

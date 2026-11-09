"""Does caching actually make the product-filter endpoint faster?

`htmx/products/filters` takes roughly 700ms in production. The expensive part is
`CatalogFilters.resolve`, which runs one option-building query per dynamic
filter. These tests run that same work with and without the cache block and
compare the two.

Needs a migrated Postgres, like the rest of the database-backed suite, so it
runs under `invoke test` rather than standalone.
"""

import statistics
import time
import typing as t

import pytest

from shared_code.data_model import DynamicFilter, DynamicSort, MethodEd, Product, ProductEd, Supplier
from shared_code.infra.database import DatabaseContext
from shared_code.modules.catalog_filters import CatalogFilters
from shared_code.modules.catalog_filters.types import ResolvedCatalogFilters
from shared_code.services.caching import CacheService, GidDep, MemoryCacheService

PRODUCT_COUNT = 150
REPEATS = 5
REQUIRED_SPEEDUP = 5.0
MEASURABLE_SECONDS = 0.001

LEVELS = (["vmbo"], ["havo"], ["vwo"], ["vmbo", "havo"], ["havo", "vwo"])


def filter_payload(resolved: ResolvedCatalogFilters) -> dict[str, t.Any]:
    """Reduce resolved filters to the plain data a template actually renders.

    Caching `ResolvedCatalogFilters` itself would drag a `QueryBuilder`, and
    through it a live database handle, into the store. Projecting first keeps
    what crosses the wire to strings and lists, which is also what makes the
    entry survive a deploy that changed the definition classes.

    `resolve()` only parses the request; the cost sits in `options()`, which
    runs one distinct-value query per dynamic filter. The handler forces those
    with `load_options()`, so asking for them here measures the same work the
    endpoint does rather than a second round of queries.
    """
    return {
        "entity_kind": resolved.entity_kind,
        "active_filter_count": resolved.active_filter_count,
        "filters": [
            {
                "slug": definition.slug,
                "label": definition.label,
                "current_value": definition.current_value,
                "options": [{"value": option.value, "label": option.label} for option in definition.options()],
            }
            for definition in resolved.filters
        ],
        "sort_options": sorted(resolved.sort_options),
    }


def resolve_payload(filters: CatalogFilters, params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Run the real filter resolution for one request and project the result."""
    resolved = filters.resolve(
        "product",
        params=params,
        option_builder=Product.where(Product.available != "verwijderd").select(Product.ALL),
        sort_options=filters.sort_options("product"),
    ).load_options()  # as the handler does, so the queries are inside the measurement
    return filter_payload(resolved)


def cached_resolve_payload(
    caching: CacheService,
    filters: CatalogFilters,
    params: dict[str, t.Any],
) -> dict[str, t.Any]:
    """Resolve filters through a cache block, exactly as a call site would."""
    with caching("product_filters", params, scope=None) as cache:
        if cache.valid:
            return t.cast(dict[str, t.Any], cache.value)

        return cache.set(resolve_payload(filters, params))


def seeded_product_gids() -> set[str]:
    """Return the gids of every product this module seeded."""
    return set(ProductEd.where(ProductEd.olid.startswith("perf-product-")).column(ProductEd.gid))


def fill_and_report_gids(caching: CacheService, filters: CatalogFilters, params: dict[str, t.Any]) -> set[str]:
    """Cache one filter payload and return the gids its queries recorded."""
    with caching("product_filters", params, scope=None) as cache:
        cache.set(resolve_payload(filters, params))
        return {dep.gid for dep in cache.deps if isinstance(dep, GidDep)}


def median_seconds(action: t.Callable[[], t.Any], repeats: int = REPEATS) -> float:
    """Return the median wall-clock cost of running an action a few times."""
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings)


@pytest.fixture()
def seeded_catalogue(
    migrated_db_per_file: None,
    db_per_file: DatabaseContext,
    monkeypatch: pytest.MonkeyPatch,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> t.Iterator[CatalogFilters]:
    """Seed a catalogue big enough that resolving its filters costs real time.

    The row factories tear down what they inserted; this only has to make sure
    the connection is left clean when a test fails partway through.
    """
    assert migrated_db_per_file is None

    suppliers = [
        supplier_factory(name=f"Perf Supplier {index}", email_domains=[f"perf-{index}.example.test"])
        for index in range(3)
    ]
    methods = [
        method_factory(
            supplier_gid=suppliers[index % len(suppliers)].gid,
            olid=f"perf-method-{index:03d}",
            name=f"Perf Method {index}",
        )
        for index in range(6)
    ]

    for index in range(PRODUCT_COUNT):
        method = methods[index % len(methods)]
        product_factory(
            supplier_gid=method.supplier_gid,
            method_gid=method.gid,
            olid=f"perf-product-{index:04d}",
            name=f"Perf Product {index}",
            levels=list(LEVELS[index % len(LEVELS)]),
        )

    for slug, label, field_name, widget in (
        ("levels", "Niveaus", "levels", "select"),
        ("subjects", "Vakken", "subjects", "select"),
        ("available", "Beschikbaarheid", "available", "select"),
        ("language", "Taal", "language", "select"),
        ("composition", "Samenstelling", "composition", "select"),
    ):
        dynamic_filter_factory(
            slug=slug,
            label=label,
            filter_kind="dynamic",
            field_name=field_name,
            applies_to="product",
            widget_kind=widget,
            sort_order=1,
        )

    dynamic_filter_factory(
        slug="q",
        label="Zoeken",
        filter_kind="search",
        applies_to="both",
        widget_kind="search",
        sort_order=0,
    )
    dynamic_sort_factory(
        slug="name-asc",
        label="Naam A-Z",
        applies_to="product",
        order_expression="name",
        sort_order=1,
        is_default=True,
    )

    db_per_file.commit()
    monkeypatch.setenv("CACHE_BACKEND", "none")

    try:
        yield CatalogFilters.with_injected(db=db_per_file)
    finally:
        db_per_file.rollback()


@pytest.fixture()
def caching(db_per_file: DatabaseContext) -> t.Iterator[MemoryCacheService]:
    """Provide a cache bound to the test database, so dependencies are recorded."""
    service = MemoryCacheService.with_injected(db=db_per_file)
    try:
        yield service
    finally:
        service.invalidate_all()


def test_cached_filter_payload_survives_serialization(
    seeded_catalogue: CatalogFilters,
    caching: MemoryCacheService,
) -> None:
    """The projected payload round-trips, so a timing failure is never a pickling one."""
    payload = resolve_payload(seeded_catalogue, {})

    assert caching.loads(caching.dumps(payload)) == payload


def test_cached_and_uncached_filters_agree(
    seeded_catalogue: CatalogFilters,
    caching: MemoryCacheService,
) -> None:
    """Caching must not change the answer, only how long it takes to get it."""
    params: dict[str, t.Any] = {"levels": ["vmbo"]}

    uncached = resolve_payload(seeded_catalogue, params)
    first = cached_resolve_payload(caching, seeded_catalogue, params)
    second = cached_resolve_payload(caching, seeded_catalogue, params)

    assert first == uncached
    assert second == uncached


def test_cached_filters_are_significantly_faster(
    seeded_catalogue: CatalogFilters,
    caching: MemoryCacheService,
) -> None:
    """The whole point of the feature: a warm filter response beats a cold one by a lot."""
    params: dict[str, t.Any] = {}

    # warm connections and any lazily defined tables, so the first call's
    # one-off cost is not attributed to the uncached measurement
    resolve_payload(seeded_catalogue, params)

    uncached = median_seconds(lambda: resolve_payload(seeded_catalogue, params))

    if uncached < MEASURABLE_SECONDS:
        pytest.skip(f"filter resolution took {uncached * 1000:.2f}ms; too fast to measure a speedup against")

    cached_resolve_payload(caching, seeded_catalogue, params)  # fill
    cached = median_seconds(lambda: cached_resolve_payload(caching, seeded_catalogue, params))

    speedup = uncached / max(cached, 1e-9)
    assert speedup >= REQUIRED_SPEEDUP, (
        f"cached filters were only {speedup:.1f}x faster "
        f"(uncached {uncached * 1000:.1f}ms, cached {cached * 1000:.1f}ms); "
        f"expected at least {REQUIRED_SPEEDUP:.0f}x"
    )


def test_invalidating_a_recorded_product_drops_the_cached_filters(
    seeded_catalogue: CatalogFilters,
    caching: MemoryCacheService,
) -> None:
    """A product the option queries actually returned can invalidate the entry."""
    params: dict[str, t.Any] = {}
    recorded = fill_and_report_gids(caching, seeded_catalogue, params)

    recorded_products = sorted(recorded & seeded_product_gids())
    assert recorded_products, "the option queries returned no product rows at all"

    assert caching.invalidate(recorded_products[0]) == 1

    with caching("product_filters", params, scope=None) as cache:
        assert not cache.valid


def test_a_product_the_option_queries_skipped_does_not_invalidate(
    seeded_catalogue: CatalogFilters,
    caching: MemoryCacheService,
) -> None:
    """Most products are never recorded, so per-gid invalidation cannot cover filter options.

    `options()` runs `DISTINCT ON (<field>)`, which returns one row per option
    value rather than one per product, and without an ORDER BY it is unspecified
    which row represents each group. Filter options depend on the *set* of
    products rather than on any single row, so they need the table-level
    invalidation that is still parked. Until that exists this route's freshness
    comes from its TTL, not from `invalidate(gid)`.
    """
    params: dict[str, t.Any] = {}
    recorded = fill_and_report_gids(caching, seeded_catalogue, params)

    unrecorded = sorted(seeded_product_gids() - recorded)
    assert unrecorded, f"expected {PRODUCT_COUNT} products to outnumber the distinct option values"

    assert caching.invalidate(unrecorded[0]) == 0

    with caching("product_filters", params, scope=None) as cache:
        assert cache.valid, "an unrecorded product must not be able to drop this entry"

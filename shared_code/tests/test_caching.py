"""Tests for the swappable cache service."""

import dataclasses as dc
import logging
import os
import threading
import typing as t
import uuid

import pytest
import redis as redis_lib

from shared_code.data_model import DynamicSort, MethodEd, Product, ProductEd, Supplier
from shared_code.data_model.mixins.effdt import ed_restore_by_id
from shared_code.data_model.setup import define_tables
from shared_code.infra.database import DatabaseContext, rebuild_model
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.products import ProductBackend
from shared_code.services.caching import (
    CacheService,
    ChainedCacheService,
    DependencyRecorder,
    GidDep,
    MemoryCacheService,
    NullCacheService,
    PostgresCacheService,
    RedisCacheService,
    RowDep,
    TableDep,
    build_key,
    scope_key,
)
from shared_code.services.caching.redis import dep_token


@dc.dataclass(frozen=True)
class FakeActor:
    """Stand-in for AuthActor, matching the ScopeIdentity protocol."""

    kind: str
    id: str | None


class ExplodingCacheService(CacheService):
    """A backend where every operation fails, to prove the block fails open."""

    def load_entry(self, key: str) -> tuple[bool, bytes | None]:
        """Fail instead of answering."""
        raise ConnectionError("no cache today")

    def store_entry(self, key: str, payload: bytes, deps: t.Any, ttl: t.Any) -> None:
        """Fail instead of storing."""
        raise ConnectionError("no cache today")

    def drop_by_gid(self, gid: str) -> int:
        """Fail instead of invalidating."""
        raise ConnectionError("no cache today")

    def drop_all(self) -> int:
        """Fail instead of flushing."""
        raise ConnectionError("no cache today")

    def drop_by_table(self, table: str, gid: str | None = None) -> int:
        """Fail instead of invalidating a table."""
        raise ConnectionError("no cache today")


class RecoveringCacheService(MemoryCacheService):
    """Memory backend that can fail invalidation and recover afterward."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_invalidation = False

    def drop_by_gid(self, gid: str) -> int:
        """Fail invalidation while the simulated outage is active."""
        if self.fail_invalidation:
            raise ConnectionError("invalidation unavailable")
        return super().drop_by_gid(gid)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def chain_of(db_per_file: DatabaseContext) -> t.Callable[..., ChainedCacheService]:
    """Build a chain from hand-picked members, wired the way endow would wire it.

    A chain built through `with_injected` takes whatever `CACHE_BACKEND` names,
    which is no use to a test that needs two specific members. Constructing it
    directly skips endow, so the one thing endow would have done, giving the
    chain its database, is done here rather than in each test.
    """

    def build(*members: CacheService) -> ChainedCacheService:
        chain = ChainedCacheService(members)
        chain.db = db_per_file
        return chain

    return build


@pytest.fixture()
def product_maker(
    db_per_file: DatabaseContext,
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
) -> t.Callable[[str], ProductEd]:
    """Create a real product, with the supplier and method it needs, by name.

    The dependency recorder only has gids to find because the real tables carry
    them, so these tests run against the real data model rather than a
    throwaway one that happens to look like it.
    """

    def make(name: str) -> ProductEd:
        slug = uuid.uuid4().hex[:8]
        supplier = supplier_factory(
            name=f"Cache Supplier {slug}",
            email_domains=[f"cache-{slug}.example.test"],
        )
        method = method_factory(
            supplier_gid=supplier.gid,
            olid=f"cache-method-{slug}",
            name=f"Cache Method {slug}",
        )
        return product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"cache-product-{slug}",
            name=name,
        )

    return make


def _redis_client() -> redis_lib.Redis:
    """Connect to the Redis the test environment provides, or skip."""
    host = os.environ.get("REDIS_CACHE_HOST") or "redis-master"
    port = int(os.environ.get("REDIS_CACHE_PORT") or 6379)
    database = int(os.environ.get("REDIS_CACHE_DB") or 1)

    client = redis_lib.Redis(
        host=host, port=port, db=database, password=os.environ.get("REDIS_PASSWORD"), socket_connect_timeout=2
    )
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as error:
        pytest.skip(f"no redis at {host}:{port}/{database}: {error}")
    return client


@pytest.fixture(params=["memory", "postgres", "redis", "chained"])
def caching(
    request: pytest.FixtureRequest,
    db_per_file: DatabaseContext,
    monkeypatch: pytest.MonkeyPatch,
) -> t.Iterator[CacheService]:
    """Yield each real backend in turn, so they all answer the same contract tests."""
    service: CacheService
    if request.param == "memory":
        service = MemoryCacheService.with_injected(db=db_per_file)
    elif request.param == "postgres":
        service = PostgresCacheService.with_injected(db=db_per_file)
    elif request.param == "chained":
        # built the way production builds it, so endow wires the members too
        monkeypatch.setenv("CACHE_BACKEND", "memory,postgres")
        service = ChainedCacheService.with_injected(db=db_per_file)
    else:
        service = RedisCacheService.with_injected(
            db=db_per_file,
            client=_redis_client(),
            prefix=f"test:cache:{uuid.uuid4().hex[:8]}",
        )

    define_tables(db_per_file, caching=service)
    try:
        yield service
    finally:
        # the database is shared for the whole file, so leave nothing behind
        service.drop_all()
        db_per_file.commit()


# ---------------------------------------------------------------------------
# Keys and scope
# ---------------------------------------------------------------------------


def test_key_is_stable_for_equal_inputs() -> None:
    """The same call site with the same arguments always lands on one key."""
    assert build_key("report", ["a", "b"], None) == build_key("report", ["a", "b"], None)


def test_key_is_stable_across_unordered_containers() -> None:
    """Sets and dicts cannot change the key just by iterating differently."""
    left = build_key("report", [{"b": 2, "a": 1}, {"x", "y"}], None)
    right = build_key("report", [{"a": 1, "b": 2}, {"y", "x"}], None)
    assert left == right


def test_list_order_still_matters() -> None:
    """An ordered argument is part of the result, so it is part of the key."""
    assert build_key("report", [["a", "b"]], None) != build_key("report", [["b", "a"]], None)


def test_scope_separates_actors() -> None:
    """Two actors never share one entry."""
    alice = FakeActor(kind="user", id="alice-gid")
    bob = FakeActor(kind="user", id="bob-gid")
    assert build_key("report", [], alice) != build_key("report", [], bob)


def test_public_scope_is_shared() -> None:
    """`scope=None` is the one scope everybody shares."""
    assert scope_key(None) == "public"


def test_a_string_scope_is_used_as_is() -> None:
    """A role or tenant is a plain string, for a coarser audience than one actor."""
    assert scope_key("role:board") == "role:board"


def test_anonymous_actor_collapses_onto_public() -> None:
    """A logged-out visitor lands on the public entry rather than one of their own."""
    anonymous = FakeActor(kind="anonymous", id=None)
    assert scope_key(anonymous) == scope_key(None)
    assert build_key("report", [], anonymous) == build_key("report", [], None)


def test_build_id_separates_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new release cannot be served an entry shaped by the previous one."""
    monkeypatch.setenv("SCHEMA_VERSION", "schema-1")
    first = build_key("report", [], None)
    monkeypatch.setenv("SCHEMA_VERSION", "schema-2")
    assert build_key("report", [], None) != first


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_caching_is_off_unless_configured(db_per_file: DatabaseContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment that never mentions the cache does not get one."""
    monkeypatch.delenv("CACHE_BACKEND", raising=False)

    assert isinstance(CacheService.with_injected(db=db_per_file), NullCacheService)


def test_unknown_backend_is_an_error(db_per_file: DatabaseContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in CACHE_BACKEND fails loudly instead of silently not caching."""
    monkeypatch.setenv("CACHE_BACKEND", "memcached")

    with pytest.raises(ValueError, match="memcached"):
        CacheService.with_injected(db=db_per_file)


def test_one_name_builds_one_backend(db_per_file: DatabaseContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single name is the backend itself, not a chain of one."""
    monkeypatch.setenv("CACHE_BACKEND", "memory")

    assert isinstance(CacheService.with_injected(db=db_per_file), MemoryCacheService)


def test_several_names_build_a_chain_in_order(db_per_file: DatabaseContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """`memory,postgres` asks memory first and keeps postgres as the fallback."""
    monkeypatch.setenv("CACHE_BACKEND", "memory, postgres")

    service = CacheService.with_injected(db=db_per_file)

    assert isinstance(service, ChainedCacheService)
    assert [type(member) for member in service.members] == [MemoryCacheService, PostgresCacheService]


def test_every_member_of_a_chain_is_built_with_the_database(
    db_per_file: DatabaseContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every member is wired by endow, so each one gets the same database."""
    monkeypatch.setenv("CACHE_BACKEND", "memory,postgres")

    service = t.cast(ChainedCacheService, CacheService.with_injected(db=db_per_file))

    assert service.db is db_per_file
    assert all(member.db is db_per_file for member in service.members)


# ---------------------------------------------------------------------------
# Chaining
# ---------------------------------------------------------------------------


def test_a_chain_reads_from_the_first_member_that_has_it(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """The slower member answers when the faster one does not have the entry."""
    fast = MemoryCacheService.with_injected(db=db_per_file)
    slow = MemoryCacheService.with_injected(db=db_per_file)
    chain = chain_of(fast, slow)

    key = build_key("report", [], None)
    slow.store_entry(key, slow.dumps("from the slow one"), set(), None)

    with chain("report", scope=None) as cache:
        assert cache.valid
        assert cache.value == "from the slow one"


def test_a_chain_writes_to_every_member(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """Both stores hold the entry, which is what makes the fallback worth having."""
    fast = MemoryCacheService.with_injected(db=db_per_file)
    slow = MemoryCacheService.with_injected(db=db_per_file)
    chain = chain_of(fast, slow)

    with chain("report", scope=None) as cache:
        cache.set("value")

    key = build_key("report", [], None)
    assert fast.load_entry(key)[0]
    assert slow.load_entry(key)[0]


def test_a_broken_member_does_not_stop_the_chain(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """Losing Redis costs latency, not correctness: the next member still answers."""
    chain = chain_of(
        ExplodingCacheService.with_injected(db=db_per_file),
        MemoryCacheService.with_injected(db=db_per_file),
    )

    with chain("report", scope=None) as cache:
        assert not cache.valid
        cache.set("value")

    with chain("report", scope=None) as cache:
        assert cache.valid, "the healthy member should have kept the value"
        assert cache.value == "value"


def test_a_chain_invalidates_everywhere(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """An entry must not survive in the fallback after being invalidated."""
    fast = MemoryCacheService.with_injected(db=db_per_file)
    slow = MemoryCacheService.with_injected(db=db_per_file)
    chain = chain_of(fast, slow)

    gid = str(uuid.uuid4())
    with chain("report", scope=None) as cache:
        cache.recorder.deps.add(GidDep(gid))
        cache.set("value")

    assert chain.invalidate(gid) == 1, "one logical entry went, counted once rather than per member"

    key = build_key("report", [], None)
    assert not fast.load_entry(key)[0]
    assert not slow.load_entry(key)[0]


def test_a_chain_does_not_serve_a_recovered_members_stale_entry(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """A failed early invalidation cannot become a stale hit after recovery."""
    fast = RecoveringCacheService.with_injected(db=db_per_file)
    slow = MemoryCacheService.with_injected(db=db_per_file)
    chain = chain_of(fast, slow)
    gid = str(uuid.uuid4())

    with chain("report", scope=None) as cache:
        cache.recorder.deps.add(GidDep(gid))
        cache.set("stale")

    fast.fail_invalidation = True
    assert chain.invalidate(gid) == 1
    fast.fail_invalidation = False

    with chain("report", scope=None) as cache:
        assert not cache.valid


def test_a_chain_locks_with_the_first_member_that_can(
    db_per_file: DatabaseContext,
    chain_of: t.Callable[..., ChainedCacheService],
) -> None:
    """A Postgres-only chain cannot lock; adding a member that can gives it one."""
    without = chain_of(PostgresCacheService.with_injected(db=db_per_file))
    assert without.take_lock("k") is None

    with_lock = chain_of(
        PostgresCacheService.with_injected(db=db_per_file),
        MemoryCacheService.with_injected(db=db_per_file),
    )
    assert with_lock.take_lock("k") is True
    assert with_lock.take_lock("k") is False, "the lock is held until it is released"

    with_lock.drop_lock("k")
    assert with_lock.take_lock("k") is True


def test_an_empty_chain_is_refused() -> None:
    """A chain of nothing would silently cache nothing."""
    with pytest.raises(ValueError, match="at least one"):
        ChainedCacheService([])


def test_a_second_postgres_instance_keeps_the_callers_transaction(
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """Binding the cache tables must not roll back work the caller has not committed.

    `try_define` on an already-bound model raises "table already defined",
    treats that as a failed migration and rolls the connection back before retrying.
    That would throw away the caller's in-flight transaction, including rows in
    tables that have nothing to do with the cache.
    """
    first = PostgresCacheService.with_injected(db=db_per_file)
    first.store_entry("k", first.dumps("value"), set(), None)

    seed = product_maker("Cache Committed")
    marker = f"Cache Uncommitted {uuid.uuid4().hex[:8]}"

    try:
        ProductEd.insert(
            supplier_gid=seed.supplier_gid,
            method_gid=seed.method_gid,
            olid=f"cache-uncommitted-{uuid.uuid4().hex[:8]}",
            name=marker,
        )
        assert ProductEd.where(ProductEd.name == marker).count() == 1

        second = PostgresCacheService.with_injected(db=db_per_file)
        assert second.load_entry("k")[0], "the cached entry survives a second instance"

        assert ProductEd.where(ProductEd.name == marker).count() == 1, "the caller's uncommitted row survives too"
    finally:
        db_per_file.rollback()


def test_postgres_reports_that_it_does_not_lock(db_per_file: DatabaseContext) -> None:
    """Single-flight is left to a faster member; the backend says so rather than pretending."""
    service = PostgresCacheService.with_injected(db=db_per_file)

    assert service.take_lock("k") is None


def test_postgres_can_clear_before_any_other_operation(db_per_file: DatabaseContext) -> None:
    """A fresh service binds its models before attempting a full clear."""
    service = PostgresCacheService.with_injected(db=db_per_file)

    service.drop_all()

    assert service._defined


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------


def test_miss_then_hit(caching: CacheService) -> None:
    """A stored value comes back valid on the next visit to the same key."""
    with caching("report", "x", scope=None) as cache:
        assert not cache.valid
        cache.set({"rows": [1, 2, 3]})

    with caching("report", "x", scope=None) as cache:
        assert cache.valid
        assert cache.value == {"rows": [1, 2, 3]}


def test_empty_result_is_cached(caching: CacheService) -> None:
    """An empty answer is an answer; it caches like any other."""
    with caching("search", "nothing", scope=None) as cache:
        cache.set([])

    with caching("search", "nothing", scope=None) as cache:
        assert cache.valid
        assert cache.value == []


def test_returning_without_set_caches_nothing(caching: CacheService) -> None:
    """A branch that skips `set` opts out, and the next call still misses."""
    with caching("report", "y", scope=None) as cache:
        assert not cache.valid

    with caching("report", "y", scope=None) as cache:
        assert not cache.valid


def test_scope_isolates_entries(caching: CacheService) -> None:
    """One actor's cached result is never served to another."""
    alice = FakeActor(kind="user", id="alice-gid")
    bob = FakeActor(kind="user", id="bob-gid")

    with caching("report", scope=alice) as cache:
        cache.set("alice-only")

    with caching("report", scope=bob) as cache:
        assert not cache.valid


def test_expired_entry_is_a_miss(caching: CacheService) -> None:
    """A stored but expired entry is not valid, which is why it is not called a hit."""
    with caching("report", "z", scope=None, ttl=-1) as cache:
        cache.set("stale")

    with caching("report", "z", scope=None) as cache:
        assert not cache.valid


def test_a_broken_payload_is_a_cache_miss(memory_caching: MemoryCacheService) -> None:
    """An incompatible serialized value is recomputed instead of exposed as None."""
    memory_caching.store_entry("broken", b"not a dill payload", set(), None)

    assert memory_caching.read("broken") == (False, None)


def test_scope_is_required(caching: CacheService) -> None:
    """A call site cannot widen its audience by forgetting an argument.

    Cast to a loose callable to make the call the way an untyped caller would:
    the type checker already refuses it, and this proves it fails at runtime too.
    """
    untyped = t.cast(t.Callable[..., t.Any], caching)

    with pytest.raises(TypeError):
        untyped("report", "x")


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_invalidate_drops_entries_that_recorded_the_gid(caching: CacheService) -> None:
    """One gid takes out every entry that depended on it."""
    gid = str(uuid.uuid4())

    with caching("report", "a", scope=None) as cache:
        cache.recorder.deps.add(GidDep(gid))
        cache.set("first")

    with caching("report", "b", scope=None) as cache:
        cache.recorder.deps.add(GidDep(gid))
        cache.set("second")

    assert caching.invalidate(gid) == 2

    for name in ("a", "b"):
        with caching("report", name, scope=None) as cache:
            assert not cache.valid


def test_invalidate_leaves_unrelated_entries_alone(caching: CacheService) -> None:
    """An entry that never saw the gid survives its invalidation."""
    wanted = str(uuid.uuid4())
    other = str(uuid.uuid4())

    with caching("report", "keep", scope=None) as cache:
        cache.recorder.deps.add(GidDep(other))
        cache.set("kept")

    with caching("report", "drop", scope=None) as cache:
        cache.recorder.deps.add(GidDep(wanted))
        cache.set("dropped")

    caching.invalidate(wanted)

    with caching("report", "keep", scope=None) as cache:
        assert cache.valid
        assert cache.value == "kept"


def test_invalidate_is_not_confused_by_a_second_round(caching: CacheService) -> None:
    """Re-storing after an invalidation re-indexes, so the next one still works."""
    gid = str(uuid.uuid4())

    for _ in range(2):
        with caching("report", "loop", scope=None) as cache:
            cache.recorder.deps.add(GidDep(gid))
            cache.set("value")
        assert caching.invalidate(gid) == 1

    with caching("report", "loop", scope=None) as cache:
        assert not cache.valid


def test_invalidate_all_empties_the_cache(caching: CacheService) -> None:
    """A full flush leaves nothing behind."""
    for name in ("one", "two", "three"):
        with caching("report", name, scope=None) as cache:
            cache.set(name)

    assert caching.invalidate_all() == 3

    with caching("report", "one", scope=None) as cache:
        assert not cache.valid


def test_invalidating_an_unknown_gid_is_harmless(caching: CacheService) -> None:
    """Invalidating something nothing depended on drops nothing and raises nothing."""
    assert caching.invalidate(str(uuid.uuid4())) == 0


# ---------------------------------------------------------------------------
# Dependency recording
# ---------------------------------------------------------------------------


def test_harvest_records_uuid_columns_and_ids(
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """Every uuid column in the raw rows becomes a gid dependency, every id a row one."""
    name = f"Cache Reader {uuid.uuid4().hex[:8]}"
    product = product_maker(name)

    recorder = DependencyRecorder(db_per_file)
    with recorder:
        Product.where(Product.name == name).collect()

    assert GidDep(product.gid) in recorder.deps
    assert GidDep(product.supplier_gid) in recorder.deps, "a plain uuid column is a dependency too"
    assert any(isinstance(dep, RowDep) and dep.table == "product" for dep in recorder.deps)


def test_recorder_stops_collecting_after_the_block(
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """Queries that run after the block are none of its business."""
    recorder = DependencyRecorder(db_per_file)
    with recorder:
        pass

    before = set(recorder.deps)
    name = f"Cache Later {uuid.uuid4().hex[:8]}"
    product_maker(name)
    Product.where(Product.name == name).collect()

    assert recorder.deps == before


def test_recorder_removes_its_hooks(db_per_file: DatabaseContext) -> None:
    """The hook lists are shared process state and must come back as they were."""
    collect_before = len(db_per_file._after_collect)
    execute_before = len(db_per_file._after_execute)

    with DependencyRecorder(db_per_file):
        assert len(db_per_file._after_collect) == collect_before + 1

    assert len(db_per_file._after_collect) == collect_before
    assert len(db_per_file._after_execute) == execute_before


def test_recorder_removes_its_hooks_after_an_error(db_per_file: DatabaseContext) -> None:
    """An exception inside the block must not leave a hook installed forever."""
    collect_before = len(db_per_file._after_collect)

    with pytest.raises(RuntimeError), DependencyRecorder(db_per_file):
        raise RuntimeError("boom")

    assert len(db_per_file._after_collect) == collect_before


def test_positional_records_seed_dependencies(
    memory_caching: MemoryCacheService,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """Caching around already-loaded rows still tracks them."""
    product_gid = product_maker(f"Cache Seeded {uuid.uuid4().hex[:8]}").gid
    product = Product.where(Product.gid == product_gid).first()

    with memory_caching("render", product, scope=None) as cache:
        cache.set("rendered")

    assert GidDep(product_gid) in cache.deps


def test_block_invalidation_uses_harvested_deps(
    memory_caching: MemoryCacheService,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """A gid picked up by the harvest is enough to invalidate the entry later."""
    name = f"Cache Listing {uuid.uuid4().hex[:8]}"
    supplier_gid = product_maker(name).supplier_gid

    with memory_caching("listing", scope=None) as cache:
        rows = Product.where(Product.name == name).collect()
        cache.set([row.name for row in rows])

    assert memory_caching.invalidate(supplier_gid) == 1

    with memory_caching("listing", scope=None) as cache:
        assert not cache.valid


def test_a_hit_records_nothing(memory_caching: MemoryCacheService) -> None:
    """A hit runs no query, so it collects no dependencies. Nested blocks are parked on this."""
    with memory_caching("listing", scope=None) as cache:
        Product.where(Product.name == "Cache Reader").collect()
        cache.set("first")

    with memory_caching("listing", scope=None) as cache:
        assert cache.valid
        assert not cache.deps


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def test_table_invalidation_preserves_other_entities(caching: CacheService) -> None:
    """Known gids clear query membership and that entity, keeping other tables."""
    entries = {
        "empty-query": {TableDep("product")},
        "changed": {TableDep("product", gid="changed")},
        "unchanged": {TableDep("product", gid="unchanged")},
        "other-table": {TableDep("supplier")},
    }
    for key, deps in entries.items():
        caching.store_entry(key, caching.dumps(key), deps, ttl=None)
    assert caching.invalidate_table("product_ed", gid="changed") == 2
    assert not caching.load_entry("empty-query")[0]
    assert not caching.load_entry("changed")[0]
    assert caching.load_entry("unchanged")[0]
    assert caching.load_entry("other-table")[0]
    assert caching.invalidate_table("product_model") == 1
    assert not caching.load_entry("unchanged")[0]
    assert caching.load_entry("other-table")[0]


def test_rebuild_invalidates_whole_table_without_clearing_other_tables(
    caching: CacheService,
    db_per_file: DatabaseContext,
) -> None:
    """Raw model rebuilds explicitly invalidate all dependencies on that model."""
    for gid in ("first", "second"):
        caching.store_entry(gid, caching.dumps(gid), {TableDep("product", gid=gid)}, ttl=300)
    caching.store_entry("supplier", caching.dumps("keep"), {TableDep("supplier")}, ttl=300)
    rebuild_model(db_per_file, "product", caching=caching)
    assert not caching.load_entry("first")[0]
    assert not caching.load_entry("second")[0]
    assert caching.load_entry("supplier")[0]


def test_insert_invalidates_cached_empty_query(
    caching: CacheService,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """An insert invalidates a query even when it had no gids to record."""
    name = f"Cache Empty {uuid.uuid4().hex}"
    with caching("empty-listing", name, scope=None) as cache:
        assert not Product.where(Product.name == name).collect()
        cache.set([])
    with caching("empty-listing", name, scope=None) as cache:
        assert cache.valid
    product = product_maker(name)
    with caching("empty-listing", name, scope=None) as cache:
        assert not cache.valid
        assert Product.where(Product.name == name).collect().first().gid == product.gid


@pytest.mark.parametrize("change", ["update", "delete"])
def test_committed_changes_invalidate_filtered_query(
    caching: CacheService,
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
    change: str,
) -> None:
    """Updates entering a filter and deletes both invalidate the query index."""
    product = product_maker(f"Cache Before {uuid.uuid4().hex}")
    name = f"Cache After {uuid.uuid4().hex}"
    with caching("filtered-listing", name, scope=None) as cache:
        cache.set(ProductEd.where(ProductEd.name == name).column(ProductEd.gid))
    if change == "update":
        ProductEd.where(ProductEd.id == product.id).update(name=name)
    else:
        ProductEd.where(ProductEd.id == product.id).delete()
    db_per_file.commit()
    with caching("filtered-listing", name, scope=None) as cache:
        assert not cache.valid
        gids = ProductEd.where(ProductEd.name == name).column(ProductEd.gid)
        assert gids == ([product.gid] if change == "update" else [])


def test_rollback_restores_postgres_cache_but_leaves_external_cache_empty(
    caching: CacheService,
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
) -> None:
    """Cache deletion follows the backend's existing transaction semantics."""
    product = product_maker(f"Cache Rollback {uuid.uuid4().hex}")
    with caching("rollback-listing", product.gid, scope=None) as cache:
        cache.set(ProductEd.where(ProductEd.gid == product.gid).column(ProductEd.name))
    db_per_file.commit()
    ProductEd.where(ProductEd.id == product.id).update(name="Uncommitted")
    db_per_file.rollback()
    with caching("rollback-listing", product.gid, scope=None) as cache:
        if isinstance(caching, (PostgresCacheService, ChainedCacheService)):
            assert cache.valid
            assert cache.value == [product.name]
        else:
            assert not cache.valid
        assert ProductEd.where(ProductEd.gid == product.gid).column(ProductEd.name) == [product.name]


@pytest.mark.parametrize("change", ["edit", "delete", "restore"])
def test_effective_dated_writes_invalidate_before_commit(
    caching: CacheService,
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
    change: str,
) -> None:
    """Edits, logical deletes and restores insert versions with the same gid."""
    product = product_maker(f"Cache Effdt {uuid.uuid4().hex}")
    product_gid = product.gid
    product_id = product.id
    product_name = product.name
    unrelated = product_maker(f"Cache Unrelated {uuid.uuid4().hex}")
    if change == "restore":
        product.delete_record()
        db_per_file.commit()
    with caching("effdt", product_gid, scope=None) as cache:
        cache.update_deps(TableDep("product", gid=product_gid))
        cache.set(product_name)
    with caching("unrelated-effdt", unrelated, scope=None) as cache:
        cache.set(unrelated.name)
    db_per_file.commit()
    with caching("effdt", product_gid, scope=None) as cache:
        assert cache.valid
    if change == "edit":
        product.update_record(name="Changed")
    elif change == "delete":
        product.delete_record()
    else:
        ed_restore_by_id(ProductEd, product_id, last_saved_by="cache-effdt-test")
    with caching("effdt", product_gid, scope=None) as cache:
        assert not cache.valid
    with caching("unrelated-effdt", unrelated, scope=None) as cache:
        assert cache.valid
        assert cache.value == unrelated.name
    current = Product.where(Product.gid == product_gid).first()
    if change == "edit":
        assert current.name == "Changed"
    elif change == "delete":
        assert current is None
    else:
        assert current.effstatus
        assert current.name == product_name
    db_per_file.commit()


def test_sort_configuration_change_reorders_cached_listing(
    memory_caching: MemoryCacheService,
    db_per_file: DatabaseContext,
    product_maker: t.Callable[[str], ProductEd],
    dynamic_sort_factory: t.Callable[..., DynamicSort],
) -> None:
    """Sort reads remain outside the list block while writes invalidate both."""
    prefix = f"Cache Sort {uuid.uuid4().hex}"
    first = product_maker(f"{prefix} A")
    second = product_maker(f"{prefix} B")
    sort = dynamic_sort_factory(
        slug="cache-sort",
        label="Cache sort",
        applies_to="product",
        order_expression="name",
        sort_order=1,
    )
    backend = ProductBackend.with_injected(
        db=db_per_file,
        caching=memory_caching,
        auth_adapter=AuthAdapter.for_service("cache-sort-test"),
    )

    def listing_gids() -> list[str]:
        rows = backend.list_public_products(sort=sort.slug, page=1, limit=10000)
        return [row.gid for row in rows if row.gid in {first.gid, second.gid}]

    assert listing_gids() == [first.gid, second.gid]
    assert listing_gids() == [first.gid, second.gid]
    sort.update_record(order_expression="~name")
    db_per_file.commit()
    assert listing_gids() == [second.gid, first.gid]


def test_lock_is_exclusive(caching: CacheService) -> None:
    """A second caller cannot take a lock the first one holds."""
    if not caching.take_lock("k"):
        pytest.skip(f"{type(caching).__name__} does not implement locking")
    caching.drop_lock("k")

    assert caching.take_lock("k") is True
    assert caching.take_lock("k") is False
    caching.drop_lock("k")
    assert caching.take_lock("k") is True


def test_lock_is_released_with_the_block(caching: CacheService) -> None:
    """Leaving a locked block frees the lock for the next caller."""
    if not caching.take_lock("probe"):
        pytest.skip(f"{type(caching).__name__} does not implement locking")
    caching.drop_lock("probe")

    with caching("slow", scope=None, lock=True) as cache:
        cache.set("value")

    assert caching.take_lock(cache.key) is True


def test_a_locked_block_still_serves_a_hit(caching: CacheService) -> None:
    """Asking for a lock costs nothing when the value is already there."""
    with caching("slow", scope=None, lock=True) as cache:
        cache.set("value")

    with caching("slow", scope=None, lock=True) as cache:
        assert cache.valid
        assert cache.value == "value"


def test_a_locked_block_waits_for_the_worker_filling_the_entry(memory_caching: MemoryCacheService) -> None:
    """A lock loser waits for the winner's value instead of recomputing it."""
    key = build_key("slow", [], None)
    entered = threading.Event()
    observed: list[tuple[bool, t.Any]] = []
    assert memory_caching.take_lock(key) is True

    def read_after_wait() -> None:
        with memory_caching("slow", scope=None, lock=True) as cache:
            observed.append((cache.valid, cache.value))
            entered.set()

    worker = threading.Thread(target=read_after_wait, daemon=True)
    worker.start()
    try:
        assert not entered.wait(timeout=0.1), "the second worker must not enter while the first is computing"
        memory_caching.store_entry(key, memory_caching.dumps("value"), set(), None)
    finally:
        memory_caching.drop_lock(key)

    assert entered.wait(timeout=2)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert observed == [(True, "value")]


# ---------------------------------------------------------------------------
# Backends that do not cache
# ---------------------------------------------------------------------------


def test_null_backend_never_serves_a_value(db_per_file: DatabaseContext) -> None:
    """Turning the cache off must not need a single call site to change."""
    service = NullCacheService.with_injected(db=db_per_file)

    with service("report", scope=None) as cache:
        cache.set("value")

    with service("report", scope=None) as cache:
        assert not cache.valid


def test_broken_backend_fails_open(db_per_file: DatabaseContext) -> None:
    """A dead cache costs latency, never correctness."""
    service = ExplodingCacheService.with_injected(db=db_per_file)
    calls = 0

    for _ in range(2):
        with service("report", scope=None) as cache:
            assert not cache.valid
            calls += 1
            cache.set("value")

    assert calls == 2, "the caller ran both times rather than seeing an exception"


def test_broken_backend_reports_itself(db_per_file: DatabaseContext, caplog: pytest.LogCaptureFixture) -> None:
    """A cache that has been dead for a week must not look like one that works."""
    service = ExplodingCacheService.with_injected(db=db_per_file)

    with caplog.at_level(logging.WARNING, logger="shared_code.services.caching.contracts"):
        with service("report", scope=None) as cache:
            cache.set("value")

    logged = [record.getMessage() for record in caplog.records]
    assert any("cache load failed" in message for message in logged)
    assert any("cache store failed" in message for message in logged)


def test_broken_backend_invalidation_is_survivable(db_per_file: DatabaseContext) -> None:
    """Invalidating through a dead backend reports nothing dropped rather than raising."""
    service = ExplodingCacheService.with_injected(db=db_per_file)

    assert service.invalidate("some-gid") == 0
    assert service.invalidate_all() == 0


# ---------------------------------------------------------------------------
# Redis specifics
# ---------------------------------------------------------------------------


def test_dep_tokens_do_not_collide() -> None:
    """A gid and a row must never encode to the same index key."""
    assert dep_token(GidDep("abc")) != dep_token(RowDep("abc", 1))
    assert dep_token(RowDep("product", 1)) != dep_token(RowDep("product", 11))


def test_redis_uses_its_own_database(db_per_file: DatabaseContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache stays off database 0, where py4web keeps its sessions."""
    monkeypatch.delenv("REDIS_CACHE_DB", raising=False)

    service = RedisCacheService.with_injected(db=db_per_file)
    assert service.client.get_connection_kwargs()["db"] == 1


def test_redis_flush_leaves_other_keys_alone(db_per_file: DatabaseContext) -> None:
    """A full flush is scoped to this cache's prefix, not the whole database."""
    client = _redis_client()
    service = RedisCacheService.with_injected(
        db=db_per_file,
        client=client,
        prefix=f"test:cache:{uuid.uuid4().hex[:8]}",
    )
    outsider = f"test:outsider:{uuid.uuid4().hex[:8]}"

    client.set(outsider, b"keep me")
    try:
        with service("report", scope=None) as cache:
            cache.set("value")

        service.invalidate_all()
        assert client.get(outsider) == b"keep me"
    finally:
        client.delete(outsider)
        service.drop_all()


def test_redis_dependency_indexes_expire_with_their_entry(db_per_file: DatabaseContext) -> None:
    """A newly created index set receives a finite TTL on its first write."""
    client = _redis_client()
    service = RedisCacheService.with_injected(
        db=db_per_file,
        client=client,
        prefix=f"test:cache:{uuid.uuid4().hex[:8]}",
    )
    gid = str(uuid.uuid4())
    key = "expiring"

    try:
        service.store_entry(key, service.dumps("value"), {GidDep(gid)}, 60)

        assert client.ttl(service.deps_key(key)) > 0
        assert client.ttl(service.index_key(dep_token(GidDep(gid)))) > 0
    finally:
        service.drop_all()

"""Tests for per-route tracking: the counters, the slow-request events and the chain."""

import json
import os
import typing as t
import uuid

import pytest
import redis as redis_lib
from common.fixtures.route_stats import (
    ENABLED_VAR,
    RouteStats,
    RouteStatsFixture,
    backend_names,
    request_signature,
)
from common.models.backend.route_stats import (
    MINIMUM_SLOW_MS,
    SLOW_MS_VAR,
    ApplogRouteStats,
    slow_request_ms,
)

DAY = "2026-01-01"


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


@pytest.fixture
def stats() -> t.Iterator[RouteStats]:
    """Provide counters under a prefix of their own."""
    prefix = f"test:routestats:{uuid.uuid4().hex[:8]}"
    client = _redis_client()
    service = RouteStats(client, prefix=prefix)
    try:
        yield service
    finally:
        keys = list(client.scan_iter(match=f"{prefix}:*", count=500))
        if keys:
            client.delete(*keys)


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def test_param_order_does_not_create_a_new_shape() -> None:
    """The same query asked in a different order is one cache entry, so one signature."""
    left = request_signature("/products", {"levels": "vmbo", "q": "algebra"}, anonymous=True)
    right = request_signature("/products", {"q": "algebra", "levels": "vmbo"}, anonymous=True)

    assert left == right


def test_different_values_are_different_shapes() -> None:
    """Two filter values mean two entries, which is the cardinality worth seeing."""
    left = request_signature("/products", {"levels": "vmbo"}, anonymous=True)
    right = request_signature("/products", {"levels": "havo"}, anonymous=True)

    assert left != right


def test_logged_in_and_logged_out_are_different_shapes() -> None:
    """A per-actor route has as many shapes as it has users; the audience has to show up."""
    anonymous = request_signature("/products", {}, anonymous=True)
    identified = request_signature("/products", {}, anonymous=False)

    assert anonymous != identified


def test_authenticated_actors_are_different_shapes() -> None:
    """Private responses for different actors must not look like one shared cache entry."""
    alice = request_signature("/profile", {}, anonymous=False, actor_id="alice")
    bob = request_signature("/profile", {}, anonymous=False, actor_id="bob")

    assert alice != bob


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_repeated_shapes_count_once_as_distinct(stats: RouteStats) -> None:
    """Ten requests over two shapes is ten requests and two distinct."""
    for index in range(10):
        signature = request_signature("/products", {"levels": ["vmbo", "havo"][index % 2]}, anonymous=True)
        stats.record(DAY, "/products", signature, seconds=0.1)

    report = stats.report(DAY)

    assert len(report) == 1
    assert report[0]["requests"] == 10
    assert report[0]["distinct"] == 2


def test_savings_rank_repeated_routes_above_unique_ones(stats: RouteStats) -> None:
    """The whole point: a slow route nobody repeats is not a cache candidate."""
    for index in range(20):
        # same shape every time, so a cache would serve 19 of these
        stats.record(DAY, "/repeated", request_signature("/repeated", {}, anonymous=True), seconds=0.1)
        # a new shape every time, so a cache would never hit
        stats.record(DAY, "/unique", request_signature("/unique", {"n": index}, anonymous=True), seconds=0.5)

    report = stats.report(DAY)
    by_route = {row["route"]: row for row in report}

    assert by_route["/unique"]["total_seconds"] > by_route["/repeated"]["total_seconds"], "the unique route is slower"
    assert report[0]["route"] == "/repeated", "but the repeated one is the better candidate"
    assert by_route["/unique"]["saved_seconds"] == 0


def test_a_day_with_nothing_recorded_reports_nothing(stats: RouteStats) -> None:
    """An empty day is an empty report rather than an error."""
    assert stats.report("1999-12-31") == []


def test_recording_never_raises() -> None:
    """A broken stats backend must not be able to fail a request."""
    unreachable = redis_lib.Redis(host="127.0.0.1", port=1, socket_connect_timeout=1)
    service = RouteStats(unreachable, prefix="test:routestats:unreachable")

    service.record(DAY, "/products", "sig", seconds=0.1)


def test_summary_totals_the_day(stats: RouteStats) -> None:
    """The tile's numbers add up the same rows the page lists."""
    stats.record(DAY, "/slow", request_signature("/slow", {"page": "1"}, anonymous=True), 0.7)
    stats.record(DAY, "/slow", request_signature("/slow", {"page": "1"}, anonymous=True), 0.7)
    stats.record(DAY, "/other", request_signature("/other", {}, anonymous=True), 0.1)

    summary = stats.summary(DAY)

    assert summary["routes"] == 2
    assert summary["requests"] == 3
    assert summary["saved_seconds"] == pytest.approx(0.7, abs=0.05)


def test_summary_of_an_empty_day_is_all_zeroes(stats: RouteStats) -> None:
    """A day with nothing recorded gives the tile something to render."""
    assert stats.summary("1999-12-31") == {
        "routes": 0,
        "requests": 0,
        "saved_seconds": 0,
    }


def test_the_report_splits_a_request_into_its_parts(stats: RouteStats) -> None:
    """Controller, template and overhead are reported apart, and add back up."""
    for _ in range(4):
        stats.record(
            DAY,
            "/htmx/products/filters",
            request_signature("/htmx/products/filters", {"level": "vmbo"}, anonymous=True),
            seconds=0.300,
            controller_seconds=0.016,
            template_seconds=0.264,
        )

    row = stats.report(DAY)[0]

    assert row["mean_controller_seconds"] == pytest.approx(0.016, abs=0.0005)
    assert row["mean_template_seconds"] == pytest.approx(0.264, abs=0.0005)
    assert row["mean_overhead_seconds"] == pytest.approx(0.020, abs=0.0005), "what is left over is the fixtures"
    assert row["mean_controller_seconds"] + row["mean_template_seconds"] + row[
        "mean_overhead_seconds"
    ] == pytest.approx(row["mean_seconds"], abs=0.001)


def test_a_route_without_a_template_reports_no_render_time(stats: RouteStats) -> None:
    """A JSON endpoint or a redirect renders nothing, and says so rather than guessing."""
    stats.record(
        DAY, "/api/ping", request_signature("/api/ping", {}, anonymous=True), seconds=0.01, controller_seconds=0.006
    )

    row = stats.report(DAY)[0]

    assert row["mean_template_seconds"] == 0
    assert row["mean_controller_seconds"] == pytest.approx(0.006, abs=0.0005)


def test_an_unmeasured_request_puts_everything_in_overhead(stats: RouteStats) -> None:
    """A route outside common()/admin() records a total only; the split must not go negative."""
    stats.record(DAY, "/raw", request_signature("/raw", {}, anonymous=True), seconds=0.05)

    row = stats.report(DAY)[0]

    assert row["mean_controller_seconds"] == 0
    assert row["mean_template_seconds"] == 0
    assert row["mean_overhead_seconds"] == pytest.approx(0.05, abs=0.0005)


def _fixtures_of(decorator: t.Callable[..., t.Any]) -> list[t.Any]:
    """Return the fixture list an `action.uses(...)` decorator closed over."""
    for cell in decorator.__closure__ or ():
        if isinstance(cell.cell_contents, list):
            return t.cast(list[t.Any], cell.cell_contents)
    raise AssertionError("no fixture list on the decorator")


def test_route_stats_runs_before_the_template_fixture() -> None:
    """Only the first fixture sees the whole request, template rendering included.

    py4web calls `on_request` forwards and `on_success` backwards, so a fixture
    late in the list stops its clock before the template renders. That is how
    this fixture came to report 16ms for a route that really took 300ms.
    """
    from common.fixtures.common import admin, common, controller_timer, route_stats
    from common.fixtures.route_stats import TimedTemplate

    original_backends = route_stats.backends
    route_stats.backends = ["redis"]
    try:
        for build in (common, admin):
            fixtures = _fixtures_of(build("logs.html"))
            assert fixtures[0] is route_stats, "route_stats must come before the template fixture"
            assert fixtures[-1] is controller_timer, "the handler timer must be last, so its window is the body alone"
            assert isinstance(fixtures[1], TimedTemplate), "the template must be the one that times itself"
    finally:
        route_stats.backends = original_backends


def test_clear_drops_one_day_and_leaves_the_others(stats: RouteStats) -> None:
    """Clearing the day on screen must not take the rest of the history with it."""
    for day in ("2026-01-01", "2026-01-02"):
        stats.record(day, "/products", request_signature("/products", {}, anonymous=True), seconds=0.1)

    assert stats.clear("2026-01-01") > 0
    assert stats.report("2026-01-01") == []
    assert len(stats.report("2026-01-02")) == 1


def test_clear_without_a_day_drops_everything(stats: RouteStats) -> None:
    """After a measurement change the old numbers are incomparable, so all of them go."""
    for day in ("2026-01-01", "2026-01-02"):
        stats.record(day, "/products", request_signature("/products", {}, anonymous=True), seconds=0.1)

    assert stats.clear() > 0
    assert stats.report("2026-01-01") == []
    assert stats.report("2026-01-02") == []
    assert stats.clear() == 0, "clearing twice is not an error"


# ---------------------------------------------------------------------------
# Choosing the sinks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", []),
        ("none", []),
        ("redis", ["redis"]),
        ("applog", ["applog"]),
        ("redis,applog", ["redis", "applog"]),
        # order is the caller's, and a repeat is not two sinks
        ("applog, redis", ["applog", "redis"]),
        ("redis,redis", ["redis"]),
        # a typo costs that sink, not the application
        ("redis,postgres", ["redis"]),
        ("nonsense", []),
        # the flag it replaces named no sink, so it records nothing
        ("1", []),
    ],
)
def test_the_chain_is_parsed_like_cache_backend(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: list[str]
) -> None:
    """`ROUTE_STATS` names its sinks in order."""
    monkeypatch.setenv(ENABLED_VAR, value)

    assert backend_names() == expected


def test_an_unset_chain_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telemetry is opt-in: no variable means no sink and no wrapper in the request path."""
    monkeypatch.delenv(ENABLED_VAR, raising=False)

    assert backend_names() == []
    assert RouteStatsFixture().enabled is False


def test_the_threshold_is_read_in_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The variable is milliseconds, because that is how a slow request is talked about."""
    monkeypatch.setenv(SLOW_MS_VAR, "250")

    assert slow_request_ms() == 250


@pytest.mark.parametrize("value", ["0", "1", "-5", "", "fast"])
def test_an_unusable_threshold_never_opens_the_floodgates(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """`0` reads as 'log everything', which on a production route fills the signal table."""
    monkeypatch.setenv(SLOW_MS_VAR, value)

    assert slow_request_ms() >= MINIMUM_SLOW_MS


# ---------------------------------------------------------------------------
# The applog sink
# ---------------------------------------------------------------------------


class FakeApplog:
    """Collect the events a sink fires, instead of queueing them."""

    def __init__(self) -> None:
        """Start with nothing fired."""
        self.events: list[dict[str, t.Any]] = []

    def try_fire(self, event: dict[str, t.Any]) -> bool:
        """Record one event and report success."""
        self.events.append(event)
        return True


@pytest.fixture
def applog() -> FakeApplog:
    """Provide a collecting applogger."""
    return FakeApplog()


def _sink(applog: FakeApplog, slow_ms: int) -> ApplogRouteStats:
    """Build the sink the way endow builds it on the backend."""
    return ApplogRouteStats.with_injected(applog=t.cast(t.Any, applog), slow_ms=slow_ms)


def _record(sink: ApplogRouteStats, seconds: float, **kwargs: t.Any) -> None:
    """Hand one request to a sink the way the fixture does."""
    sink.record(
        DAY,
        kwargs.pop("route", "/products"),
        request_signature("/products", {}, anonymous=True),
        seconds=seconds,
        **kwargs,
    )


def test_a_fast_request_is_not_worth_an_event(applog: FakeApplog) -> None:
    """Below the threshold there is nothing to look into, and events cost storage."""
    sink = _sink(applog, slow_ms=1000)

    _record(sink, seconds=0.999)

    assert applog.events == []


def test_a_slow_request_is_logged_once(applog: FakeApplog) -> None:
    """One event per slow request, not one per sink call."""
    sink = _sink(applog, slow_ms=1000)

    _record(sink, seconds=1.0)
    _record(sink, seconds=2.5)

    assert len(applog.events) == 2
    assert {event["action"] for event in applog.events} == {"slow_request"}


def test_the_event_carries_the_parts_rather_than_the_signature(applog: FakeApplog) -> None:
    """A packed signature feeds a HyperLogLog; a table wants the parts to group by."""
    sink = _sink(applog, slow_ms=500)

    sink.record(
        DAY,
        "/htmx/products/filters",
        request_signature("/htmx/products/filters", {"level": "vmbo"}, anonymous=True),
        seconds=1.2,
        controller_seconds=0.9,
        template_seconds=0.2,
        params={"level": "vmbo"},
        anonymous=True,
    )

    details = applog.events[0]["details"]
    assert details["route"] == "/htmx/products/filters"
    assert details["params"] == {"level": "vmbo"}
    assert details["total_ms"] == pytest.approx(1200, abs=1)
    assert details["controller_ms"] == pytest.approx(900, abs=1)
    assert details["template_ms"] == pytest.approx(200, abs=1)
    assert details["overhead_ms"] == pytest.approx(100, abs=1), "what is left over is the fixtures"
    assert details["threshold_ms"] == 500, "so a query can tell slow from a lowered bar"


def test_the_event_names_nobody(applog: FakeApplog) -> None:
    """Who was waiting did not make the route slow, so the actor stays out of the row.

    The audience does not: a per-actor route and a shared one are slow for
    different reasons, and that is a bucket rather than an identity.
    """
    sink = _sink(applog, slow_ms=100)
    actor_gid = str(uuid.uuid4())

    _record(sink, seconds=0.5, anonymous=False, actor_id=actor_gid)

    event = applog.events[0]
    assert "user_gid" not in event
    assert actor_gid not in json.dumps(event, default=str), "not under any other key either"
    assert event["details"]["anonymous"] is False


def test_an_unreachable_applog_never_raises() -> None:
    """A full queue or a missing backend must not be able to fail a request."""

    class Broken(FakeApplog):
        """An applogger whose queue is full."""

        def try_fire(self, event: dict[str, t.Any]) -> bool:
            """Fail the way a full deque does."""
            raise RuntimeError("queue full")

    sink = _sink(Broken(), slow_ms=MINIMUM_SLOW_MS)

    _record(sink, seconds=1.0)


# ---------------------------------------------------------------------------
# Fanning out
# ---------------------------------------------------------------------------


class RecordingSink:
    """A sink that remembers what it was handed."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.calls: list[dict[str, t.Any]] = []

    def record(self, day: str, route: str, signature: str, seconds: float, **kwargs: t.Any) -> None:
        """Keep one call for inspection."""
        self.calls.append({"day": day, "route": route, "signature": signature, "seconds": seconds, **kwargs})


def test_one_broken_sink_does_not_cost_the_others(default_app_request_context: None) -> None:
    """`redis,applog` still records through the half that works."""

    class Broken:
        def record(self, *args: t.Any, **kwargs: t.Any) -> None:
            raise RuntimeError("no connection")

    working = RecordingSink()
    fixture = RouteStatsFixture(sinks=[t.cast(t.Any, Broken()), working])
    context: dict[str, t.Any] = {}

    fixture.on_request(context)
    fixture.on_success(context)

    assert len(working.calls) == 1


def test_both_sinks_see_the_same_measurement(default_app_request_context: None) -> None:
    """The request is measured once and handed on, so the two never disagree."""
    left, right = RecordingSink(), RecordingSink()
    fixture = RouteStatsFixture(sinks=[left, right])
    context: dict[str, t.Any] = {}

    fixture.on_request(context)
    fixture.on_success(context)

    assert left.calls[0]["signature"] == right.calls[0]["signature"]
    assert left.calls[0]["seconds"] == right.calls[0]["seconds"]


def test_an_inert_fixture_records_nothing(default_app_request_context: None) -> None:
    """With no sink the clock is never even started."""
    fixture = RouteStatsFixture(sinks=[])
    context: dict[str, t.Any] = {}

    fixture.on_request(context)
    fixture.on_success(context)

    assert context == {}
    assert fixture.enabled is False


def test_only_the_redis_sink_can_answer_the_admin_page(stats: RouteStats) -> None:
    """The cache-candidates page hides unless there are counters to page through."""
    assert RouteStatsFixture(sinks=[_sink(FakeApplog(), slow_ms=MINIMUM_SLOW_MS)]).stats is None
    assert RouteStatsFixture(sinks=[stats]).stats is stats

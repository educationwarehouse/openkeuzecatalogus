"""The py4web fixtures that do the measuring, and hand the result to every sink."""

import datetime as dt
import logging
import time
import typing as t

from py4web.core import Fixture, Template

from py4web import request
from shared_code.data_model import AnyDict
from shared_code.util.types import MultiValue

from .contracts import RouteStatsSink, backend_names, request_signature
from .redis_sink import RouteStats

logger = logging.getLogger(__name__)

# py4web hands every fixture in one request the same context dict, so timings ride
# along in it rather than on the fixture, which is a process-wide singleton
STARTED_AT = "route_stats.started_at"
CONTROLLER_SECONDS = "route_stats.controller_seconds"
TEMPLATE_SECONDS = "route_stats.template_seconds"


def sink_for(name: str) -> RouteStatsSink | None:
    """Return the sink one `ROUTE_STATS` name stands for, or None for an unknown name."""
    match name:
        case "redis":
            return RouteStats.from_env()
        case "applog":
            # the only local import here: the backend graph is built after this
            # module, and reaching it at module scope closes a cycle
            from ...models import backend

            return backend.route_stats
        case _:
            return None


class TimedTemplate(Template):
    """A template that reports how long it took to render itself.

    Rendering is one call, `Template.on_success`, so timing it here is exact and
    survives anyone reordering the fixtures. Inferring it from the gap between
    two neighbouring fixtures would not.
    """

    def on_success(self, context: AnyDict) -> None:
        """Render, and leave the cost behind for the counters to pick up."""
        started_at = time.perf_counter()
        try:
            super().on_success(context)
        finally:
            context[TEMPLATE_SECONDS] = context.get(TEMPLATE_SECONDS, 0.0) + (time.perf_counter() - started_at)


class ControllerTimerFixture(Fixture):
    """Measure the handler body alone.

    py4web runs `on_request` forwards and `on_success` backwards, so the last
    fixture in the list is the only one whose window is the handler and nothing
    else: its `on_request` is the last thing before the body and its
    `on_success` the first thing after.
    """

    def on_request(self, context: AnyDict) -> None:
        """Start the clock as the handler is about to run."""
        context[STARTED_AT + ".controller"] = time.perf_counter()

    def on_success(self, context: AnyDict) -> None:
        """Stop the clock now the handler has returned."""
        self._stop(context)

    def on_error(self, context: AnyDict) -> None:
        """A handler that raised still spent the time it spent."""
        self._stop(context)

    @staticmethod
    def _stop(context: AnyDict) -> None:
        """Record the handler's duration, if its start was reached."""
        started_at = context.get(STARTED_AT + ".controller")
        if started_at is not None:
            context[CONTROLLER_SECONDS] = time.perf_counter() - started_at


class RouteStatsFixture(Fixture):
    """Record route, request shape and duration for every request that passes through."""

    def __init__(
        self,
        sinks: MultiValue[RouteStatsSink] | None = None,
        backends: MultiValue[str] | None = None,
    ) -> None:
        """Wire the fixture to its sinks, or leave it inert.

        Passing `sinks` settles the question outright, which is what a test wants;
        otherwise `ROUTE_STATS` decides, and the sinks are built on first use.
        """
        super().__init__()
        self._sinks: list[RouteStatsSink] | None = None if sinks is None else list(sinks)
        if backends is not None:
            self.backends = list(backends)
        elif self._sinks is not None:
            # the caller named the sinks, so they, not the environment, say what runs
            self.backends = ["redis" if isinstance(sink, RouteStats) else "applog" for sink in self._sinks]
        else:
            self.backends = backend_names()

    @property
    def enabled(self) -> bool:
        """Report whether anything is being recorded at all.

        What the timing fixtures key off: with no sink there is nobody to report
        to, and no wrapper belongs in the request path.
        """
        return bool(self._sinks) if self._sinks is not None else bool(self.backends)

    @property
    def sinks(self) -> list[RouteStatsSink]:
        """Build the sinks lazily, so an inert fixture never opens a connection."""
        if self._sinks is None:
            self._sinks = [sink for name in self.backends if (sink := self._build(name)) is not None]
        return self._sinks

    @property
    def stats(self) -> RouteStats | None:
        """Return the sink that can be read back, when one is configured.

        Only the Redis counters can answer the cache-candidates page; with
        `ROUTE_STATS=applog` there is nothing to page through, and the admin page
        hides on this being None.
        """
        return next((sink for sink in self.sinks if isinstance(sink, RouteStats)), None)

    @staticmethod
    def _build(name: str) -> RouteStatsSink | None:
        """Construct one named sink, or nothing if it cannot be reached.

        A sink that fails to build takes itself out of the chain rather than the
        request with it, so `ROUTE_STATS=redis,applog` still records through the
        half that works.
        """
        try:
            return sink_for(name)
        except Exception as error:  # telemetry must never break a request
            logger.warning("route stats backend %r unavailable: %s: %s", name, type(error).__name__, error)
            return None

    def on_request(self, context: AnyDict) -> None:
        """Start the clock, on the request's own context rather than on self."""
        if self.enabled:
            context[STARTED_AT] = time.perf_counter()

    def on_success(self, context: AnyDict) -> None:
        """Record a request that produced a response."""
        self._record(context)

    def on_error(self, context: AnyDict) -> None:
        """Record a failed request too; a slow error is still slow."""
        self._record(context)

    def _record(self, context: AnyDict) -> None:
        started_at = context.pop(STARTED_AT, None)

        sinks = self.sinks
        if not sinks or started_at is None:
            return

        seconds = time.perf_counter() - started_at
        route = str(request.path or "/")
        params: dict[str, t.Any] = dict(request.query or {})

        anonymous, actor_id = self._actor_identity()
        day = dt.date.today().isoformat()
        signature = request_signature(route, params, anonymous=anonymous, actor_id=actor_id)
        controller_seconds = float(context.get(CONTROLLER_SECONDS) or 0.0)
        template_seconds = float(context.get(TEMPLATE_SECONDS) or 0.0)

        for sink in sinks:
            try:
                sink.record(
                    day=day,
                    route=route,
                    signature=signature,
                    seconds=seconds,
                    controller_seconds=controller_seconds,
                    template_seconds=template_seconds,
                    params=params,
                    anonymous=anonymous,
                    actor_id=actor_id,
                )
            except Exception as error:  # one broken sink must not cost the others
                logger.warning("route stats sink %s failed: %s: %s", type(sink).__name__, type(error).__name__, error)

    @staticmethod
    def _actor_identity() -> tuple[bool, str | None]:
        """Return whether the actor is anonymous and their stable identifier."""
        try:
            from ...models import auth_context

            actor = auth_context.actor
            return actor.kind == "anonymous", actor.id
        except Exception:  # telemetry must never break a request
            return True, None


route_stats = RouteStatsFixture()
controller_timer = ControllerTimerFixture()

"""Homepage timeline presentation with persisted event rows."""

import datetime as dt

from apps._default.models.timeline import event_summary, timeline_context
from common.models import db

from shared_code.data_model import TimelineEvent


def test_timeline_context_groups_and_orders_saved_events() -> None:
    """Year and quarter groups contain the newest saved events first."""
    try:
        older = TimelineEvent.insert(
            title="Earlier report",
            source_type="rapport",
            author="Editor",
            event_date=dt.date(2025, 2, 1),
            url="https://example.org/earlier",
        )
        newer = TimelineEvent.insert(
            title="Later report",
            source_type="rapport",
            author="Editor",
            event_date=dt.date(2025, 3, 1),
            url="https://example.org/later",
            description="A saved description.",
        )
        next_year = TimelineEvent.insert(
            title="Next year",
            source_type="blog",
            author="Editor",
            event_date=dt.date(2026, 1, 1),
            url="https://example.org/next-year",
        )

        events = (
            TimelineEvent.where(TimelineEvent.id.belongs((older.id, newer.id, next_year.id)))
            .orderby(TimelineEvent.event_date)
            .collect()
        )
        context = timeline_context(events)

        assert [year["year"] for year in context["years"]] == [2025, 2026]
        assert [(period["year"], period["quarter"]) for period in context["periods"]] == [(2025, 1), (2026, 1)]
        assert [event.id for event in context["periods"][0]["events"]] == [newer.id, older.id]
        assert [event.id for event in context["periods"][1]["events"]] == [next_year.id]
        assert event_summary(events.first()) == "Open de oorspronkelijke bijdrage."
        assert event_summary(newer) == "A saved description."
    finally:
        db.rollback()

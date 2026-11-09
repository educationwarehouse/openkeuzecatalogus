"""Arrange persisted timeline events for the two public homepage views."""

import typing as t
from collections import defaultdict

from shared_code.data_model import TimelineEvent

SOURCE_TYPE_LABELS = {
    "blog": "Blog",
    "pers": "Persbericht",
    "rapport": "Rapport",
    "social media": "Social media",
}


class TimelineYear(t.TypedDict):
    year: int
    offset: int
    events: list[TimelineEvent]


class TimelinePeriod(t.TypedDict):
    year: int
    quarter: int
    column: int
    events: list[TimelineEvent]


class TimelineContext(t.TypedDict):
    years: list[TimelineYear]
    periods: list[TimelinePeriod]
    columns: str
    width: int
    type_labels: dict[str, str]


def timeline_context(events: t.Iterable[TimelineEvent]) -> TimelineContext:
    """Build year anchors and period columns from the current database rows."""
    by_period: dict[tuple[int, int], list[TimelineEvent]] = defaultdict(list)
    for event in events:
        quarter = (event.event_date.month - 1) // 3 + 1
        by_period[(event.event_date.year, quarter)].append(event)

    years: list[TimelineYear] = []
    periods: list[TimelinePeriod] = []
    tracks: list[int] = []
    offset = 0
    previous_year = None
    for (year, quarter), period_events in sorted(by_period.items()):
        if previous_year is not None and year != previous_year:
            tracks.append(8)
            offset += 8 + 24
        if year != previous_year:
            years.append({"year": year, "offset": offset, "events": []})
        period_events.sort(key=lambda event: (event.event_date, event.id), reverse=True)
        years[-1]["events"].extend(period_events)
        periods.append({"year": year, "quarter": quarter, "column": len(tracks) + 1, "events": period_events})
        tracks.append(400)
        offset += 400 + 24
        previous_year = year

    width = sum(tracks) + 24 * max(0, len(tracks) - 1)
    return {
        "years": years,
        "periods": periods,
        "columns": " ".join(f"{track}px" for track in tracks),
        "width": width,
        "type_labels": SOURCE_TYPE_LABELS,
    }


def event_summary(event: TimelineEvent) -> str:
    """Return a short card excerpt while keeping the full text in the dialog."""
    description = (event.description or "").strip() or "Open de oorspronkelijke bijdrage."
    return description if len(description) <= 100 else description[:99].rstrip() + "…"

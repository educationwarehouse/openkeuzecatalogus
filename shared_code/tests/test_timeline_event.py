"""Database coverage for public homepage timeline events."""

import datetime as dt

from typedal import TypeDAL

from shared_code.data_model import TimelineEvent


def test_timeline_event_round_trip(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """An event has a generated ID and persists its card and modal content."""
    assert migrated_db_per_file is None

    event = TimelineEvent.insert(
        title="Onderwijs in beweging",
        source_type="rapport",
        author="Onderwijsraad",
        event_date=dt.date(2026, 9, 24),
        url="https://example.org/rapport",
        description="Een beschrijving voor de tijdlijn.",
    )
    db_per_file.commit()

    saved = TimelineEvent.where(TimelineEvent.id == event.id).collect().first()
    assert saved is not None
    assert saved.gid is not None
    assert saved.title == "Onderwijs in beweging"
    assert saved.source_type == "rapport"
    assert saved.author == "Onderwijsraad"
    assert saved.event_date == dt.date(2026, 9, 24)
    assert saved.url == "https://example.org/rapport"
    assert saved.description == "Een beschrijving voor de tijdlijn."


def test_timeline_event_rejects_unknown_source_type(migrated_db_per_file: None) -> None:
    """The admin model only accepts the four timeline source categories."""
    assert migrated_db_per_file is None

    row, errors = TimelineEvent.validate_and_insert(
        title="Onbekende bron",
        source_type="boek",
        author="Redactie",
        event_date=dt.date(2026, 9, 24),
        url="https://example.org/bron",
    )

    assert row is None
    assert "source_type" in errors

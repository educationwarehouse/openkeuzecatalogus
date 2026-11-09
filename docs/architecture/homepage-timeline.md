# Homepage discussion timeline

The discussion timeline on `/` is stored in the `timeline_event` table. The
`create_timeline_event_table_20260924_001` migration creates it. The following
`seed_timeline_events_20260924_002` migration imports the 296 contributions
that were previously embedded in the homepage template.
The import source is `migrate/data/seeding/timeline-events.jsonl`. Its rows are
an initial snapshot, not a source read by the live website after migration.

Each event has a title, source type (`blog`, `pers`, `rapport`, or
`social media`), author or organisation, event date, source URL, and full
description. The database ID identifies the same event in the compact marker,
full card, and description endpoint. The quarter and year are derived from the
date. The short card excerpt is derived from the description.

Admins open **Catalogusinstellingen > Tijdlijn** to manage events at
`/admin/timeline` using the standard CRUD grid. The
homepage builds its compact and full views from current database rows on each
request. The modal fetches descriptions from
`/data/discussion-descriptions.json`, which also reads current database rows.
Normal database backups therefore include timeline edits.

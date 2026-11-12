# Catalogue participation

## Import

Administrators upload a UTF-8, comma-separated CSV at **Leermiddelen > Catalogusdeelname
importeren** (`/admin/supplier-catalogue-import`), review supplier matches and statuses,
then confirm. Rows can be skipped and missing suppliers created.

The required columns are `officiele_naam` (the client's supplier name), `edu_v_naam`
(the platform supplier name), and `status`. Column order is free and extra columns
are ignored. A downloadable example covers all four statuses.

The Edu-V name is matched against normalized platform and endpoint publisher names.
Ambiguous matches require a manual selection. New suppliers use the Edu-V name;
the official name is shown for reference during review and is not stored separately.
Other supplier fields and suppliers outside the upload are preserved. Reimporting
unchanged data has no effect. Uploads are limited to 5 MB and 1000 suppliers.

## Statuses

Statuses can be overridden during import or in the supplier editor.

| CSV status         | Stored status     |
| ------------------ | ----------------- |
| Beschikbaar        | `participating`   |
| Binnenkort gedeeld | `soon`            |
| In gesprek         | `in_conversation` |
| Onbekend           | `unknown`         |

Status values are case-insensitive and surrounding whitespace is ignored. Missing
or invalid statuses are rejected with a row number rather than guessed.

## Widget

Product and method overviews show **Beschikbaar**, **Binnenkort gedeeld** and
**In gesprek**, with counts and alphabetically sorted supplier names.

Public products determine availability, overriding stored status. Otherwise only
`soon` and `in_conversation` appear. Each supplier appears once; `participating`
without public products does not qualify as available.

The card sits beside the catalogue heading. Both the coloured segments and their
legend labels open a supplier list, anchored below the bar on desktop and displayed
as a modal bottom sheet on mobile. The sheet occupies at most 60% of the viewport;
long lists scroll inside it. Close it with the close button, Escape or a click outside.
Empty categories remain available and explain that no suppliers are listed.

Administrators can edit the title, introduction, contact text and link, and empty
category message with Content Editable. These regions share the
`components/catalogue_participation` scope across both catalogue pages. The empty
message is edited on the card in edit mode and projected into each empty list;
the category dialogs stay closed while editing so the editor tools remain usable.
Counts, category labels and supplier names remain backend-managed.

The design includes expected sharing dates, but the backend currently supplies only
supplier names and participation statuses. No dates are displayed until those are
available from the data model.

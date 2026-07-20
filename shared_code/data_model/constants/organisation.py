"""Organisation-domain constants."""

from enum import StrEnum

ORG_TYPE_LABELS = {
    "board": "Bestuur",
    "school": "School",
    "location": "Vestiging",
    "supplier": "Leverancier",
}


class OrganisationType(StrEnum):
    """Supported organisation types."""

    BOARD = "board"
    SCHOOL = "school"
    LOCATION = "location"

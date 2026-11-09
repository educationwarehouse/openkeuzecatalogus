"""Constants for the guided learning-material decision process."""

PROCESS_STAGES = {
    "new": "Nieuw",
    "board": "Bestuur",
    "school": "Schoolleiding",
    "team": "Team",
    "done": "Afgerond",
}
MATERIAL_TYPES = {
    "bought": "Ingekocht",
    "created": "Zelfgemaakt",
    "other": "Anders",
}


PROS_AND_CONS_TYPES = {
    "pro": "Pluspunt",
    "con": "Minpunt",
}

# todo: pick real limit
# I've set it to 10 queries per theme for now as a baseline.
AI_QUERY_LIMIT = 12 * 10

__all__ = ["AI_QUERY_LIMIT", "MATERIAL_TYPES", "PROCESS_STAGES", "PROS_AND_CONS_TYPES"]

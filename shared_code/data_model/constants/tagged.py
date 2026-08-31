"""Tagged relationship constants."""

from enum import StrEnum


class Predicate(StrEnum):
    """Canonical predicates used in the shared tagged graph."""

    BUNDLES = "bundles"
    IS_BOARD_OF = "IS_BOARD_OF"
    IS_SCHOOL_OF = "IS_SCHOOL_OF"

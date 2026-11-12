"""Comparison rules for supplier-provided school subject names."""

import typing as t


def normalize_school_subject(value: str) -> str:
    """Compare names regardless of case and of leading, trailing or repeated whitespace."""
    return " ".join(value.split()).casefold()


def preferred_spelling(values: t.Iterable[str]) -> str:
    """Pick a stable display spelling, preferring mixed case over all-caps variants."""
    spellings = {" ".join(value.split()) for value in values}
    return min(spellings, key=lambda spelling: (spelling.isupper(), spelling))

"""Typed template payloads for public method and product comparisons."""

import typing as t

from shared_code.modules.visions.types import VisionIds


class ComparisonField(t.TypedDict):
    """One public model field displayed across all selected records."""

    name: str
    label: str
    values: list[str]
    different: bool


class ComparisonVision(t.TypedDict):
    """One education-quality theme displayed across all selected records."""

    theme: str
    values: list[ComparisonVisionValue]
    different: bool


class ComparisonVisionValue(t.TypedDict):
    """A resolved vision value for one selected record."""

    source: str
    content: str
    properties: str


class ComparisonRecord(t.TypedDict):
    """One selected catalogue record used as a comparison column heading."""

    name: str


class ComparisonPage(t.TypedDict):
    """Data needed to render a public comparison page."""

    records: list[ComparisonRecord]
    fields: list[ComparisonField]
    visions: list[ComparisonVision]
    missing_count: int


__all__ = [
    "ComparisonField",
    "ComparisonPage",
    "ComparisonRecord",
    "ComparisonVision",
    "ComparisonVisionValue",
    "VisionIds",
]

"""Values and usage summaries for supported school subjects."""

import dataclasses as dc
import typing as t

from .names import preferred_spelling


class SchoolSubjectConflictError(ValueError):
    """A standard name or alias that another supported subject already uses."""

    def __init__(self, message: str, field: t.Literal["name", "aliases"]) -> None:
        """Remember which form field caused the conflict."""
        super().__init__(message)
        self.field = field


class SchoolSubjectValues(t.TypedDict):
    """Editable, validated fields shared by course-management actions."""

    name: str
    aliases: list[str]


class SchoolSubjectUsage(t.TypedDict):
    """Number of materials sharing one decoded list of source subject names."""

    subjects: list[str]
    material_count: int


@dc.dataclass
class UnmatchedSchoolSubject:
    """One unknown normalized name with its source spellings and usage counts."""

    value: str
    raw_values: set[str] = dc.field(default_factory=set)
    product_count: int = 0
    method_count: int = 0

    @property
    def label(self) -> str:
        """Use a stable source spelling for the reconciliation screen."""
        return preferred_spelling(self.raw_values)

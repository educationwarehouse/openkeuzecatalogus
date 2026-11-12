"""Supported school subjects and reconciliation of supplier-provided names."""

from .module import (
    clean_school_subject_values,
    create_school_subject,
    match_school_subject,
    school_subject_name_lookup,
    school_subjects_using,
    unmatched_school_subjects,
)
from .names import normalize_school_subject, preferred_spelling
from .types import SchoolSubjectConflictError, SchoolSubjectValues, UnmatchedSchoolSubject

__all__ = [
    "SchoolSubjectConflictError",
    "SchoolSubjectValues",
    "UnmatchedSchoolSubject",
    "clean_school_subject_values",
    "create_school_subject",
    "match_school_subject",
    "normalize_school_subject",
    "preferred_spelling",
    "school_subject_name_lookup",
    "school_subjects_using",
    "unmatched_school_subjects",
]

"""Typed payloads for the FAQ seed conversion."""

import typing as t


class FaqSeedQuestion(t.TypedDict):
    """One question converted from the FAQ seed file."""

    question: str
    answer: str
    show_on_homepage: bool
    sort_order: int


class FaqSeedSection(t.TypedDict):
    """One section with its questions, converted from the FAQ seed file."""

    title: str
    sort_order: int
    questions: list[FaqSeedQuestion]

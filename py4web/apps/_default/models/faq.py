"""Arrange persisted FAQ content for the public FAQ page and homepage preview."""

import typing as t

from shared_code.data_model import FaqQuestion, FaqSection
from shared_code.util.html import markdown_to_text

FAQ_INTRO = "Veelgestelde vragen over de Open Keuzecatalogus Leermiddelen"


class FaqQuestionContext(t.TypedDict):
    """One question with its precomputed search text."""

    row: FaqQuestion
    search_text: str


class FaqSectionContext(t.TypedDict):
    """One titled section with its questions."""

    title: str
    questions: list[FaqQuestionContext]


class FaqPageContext(t.TypedDict):
    """Template values for the public FAQ page."""

    intro: str
    sections: list[FaqSectionContext]
    questions: list[FaqQuestionContext]


def _question_context(question: FaqQuestion) -> FaqQuestionContext:
    """Build the template item for one question, including its plain-text search form."""
    answer_text = markdown_to_text(question.answer or "")
    return {
        "row": question,
        "search_text": f"{question.question} {answer_text}".lower(),
    }


def faq_page_context() -> FaqPageContext:
    """Group all questions by section for the FAQ page."""
    sections = FaqSection.orderby(FaqSection.sort_order, FaqSection.id).collect()
    questions = FaqQuestion.orderby(FaqQuestion.sort_order, FaqQuestion.id).collect()

    questions_by_section: dict[str, list[FaqQuestionContext]] = {section.gid: [] for section in sections}
    flat: list[FaqQuestionContext] = []
    for question in questions:
        item = _question_context(question)
        flat.append(item)
        if question.section_gid in questions_by_section:
            questions_by_section[question.section_gid].append(item)

    return {
        "intro": FAQ_INTRO,
        "sections": [{"title": section.title, "questions": questions_by_section[section.gid]} for section in sections],
        "questions": flat,
    }


def homepage_faq_preview() -> list[FaqQuestionContext]:
    """Return the questions flagged for the homepage preview, in display order."""
    questions = (
        FaqQuestion.where(FaqQuestion.show_on_homepage == True)
        .join(FaqQuestion.section, method="inner")
        .orderby(FaqSection.sort_order, FaqSection.id, FaqQuestion.sort_order, FaqQuestion.id)
        .collect()
    )
    return [_question_context(question) for question in questions]

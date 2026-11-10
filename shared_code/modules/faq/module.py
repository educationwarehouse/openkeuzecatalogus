"""Convert the static FAQ seed file into ordered sections and questions."""

import typing as t

from shared_code.data_model import AnyDict

from .types import FaqSeedQuestion, FaqSeedSection


def _answer_to_markdown(blocks: t.Iterable[AnyDict]) -> str:
    """Convert the structured answer blocks from the seed file to a markdown body."""
    parts = []
    for block in blocks:
        if block.get("type") == "ul":
            parts.append("\n".join(f"- {item}" for item in block.get("items", [])))
        else:
            parts.append(str(block.get("text", "")))
    return "\n\n".join(parts)


def parse_faq_seed(payload: AnyDict) -> list[FaqSeedSection]:
    """Convert the faq.json payload into ordered sections with markdown answers.

    The first `landing_preview_count` questions are flagged for the homepage preview,
    matching the questions the static homepage block used to show.
    """
    preview_count = int(payload.get("landing_preview_count") or 0)
    sections: list[FaqSeedSection] = []
    question_count = 0
    for section_index, category in enumerate(payload.get("categories", []), start=1):
        questions: list[FaqSeedQuestion] = []
        for question_index, question in enumerate(category.get("questions", []), start=1):
            question_count += 1
            questions.append(
                FaqSeedQuestion(
                    question=str(question.get("q") or ""),
                    answer=_answer_to_markdown(question.get("a", [])),
                    show_on_homepage=question_count <= preview_count,
                    sort_order=question_index,
                )
            )
        sections.append(
            FaqSeedSection(
                title=str(category.get("title") or ""),
                sort_order=section_index,
                questions=questions,
            )
        )
    return sections

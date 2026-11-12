"""Tests for the admin-managed FAQ sections, questions and seed conversion."""

import psycopg2.errors
import pytest
from typedal import TypeDAL

from shared_code.data_model import FaqQuestion, FaqSection
from shared_code.modules.faq import parse_faq_seed
from shared_code.util.html import markdown_to_text


def test_faq_section_round_trip(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """A section persists its title and ordering."""
    assert migrated_db_per_file is None

    section = FaqSection.insert(title="Over de catalogus", sort_order=1)
    db_per_file.commit()

    saved = FaqSection.where(FaqSection.id == section.id).collect().first()
    assert saved is not None
    assert saved.gid is not None
    assert saved.title == "Over de catalogus"
    assert saved.sort_order == 1


def test_faq_question_round_trip(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """A question persists its markdown answer, homepage flag and section reference."""
    section = FaqSection.insert(title="Sectie", sort_order=1)
    question = FaqQuestion.insert(
        section_gid=section.gid,
        question="Wat is de Open Keuzecatalogus?",
        answer="**Markdown** antwoord",
        show_on_homepage=True,
        sort_order=1,
    )
    db_per_file.commit()

    saved = FaqQuestion.where(FaqQuestion.id == question.id).join("section").collect().first()
    assert saved is not None
    assert saved.section_gid == section.gid
    assert saved.section.title == "Sectie"
    assert saved.question == "Wat is de Open Keuzecatalogus?"
    assert saved.answer == "**Markdown** antwoord"
    assert saved.show_on_homepage is True
    assert saved.sort_order == 1


def test_faq_question_defaults(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """A new question is hidden from the homepage and starts at the first position."""
    section = FaqSection.insert(title="Sectie", sort_order=1)
    question = FaqQuestion.insert(section_gid=section.gid, question="Vraag", answer="Antwoord")
    db_per_file.commit()

    saved = FaqQuestion.where(FaqQuestion.id == question.id).collect().first()
    assert saved is not None
    assert saved.show_on_homepage is False
    assert saved.sort_order == 0


def test_methods_faq_question_is_linkable_after_migration(migrated_db_per_file: None) -> None:
    """The migrated method explanation closes its section and keeps a stable anchor."""
    assert migrated_db_per_file is None

    question = FaqQuestion.where(FaqQuestion.slug == "waarom-geen-methodes").join("section").collect().first()

    assert question is not None
    assert question.question == "Waarom geen overzicht van methodes?"
    assert question.section.title == "Over de Open Keuzecatalogus"
    assert question.show_on_homepage is False
    assert "[→ Naar pakketten](/pakketten)" in question.answer
    assert "[→ Naar losse producten](/producten)" in question.answer

    section_sort_orders = FaqQuestion.where(FaqQuestion.section_gid == question.section_gid).column(
        FaqQuestion.sort_order
    )
    assert question.sort_order == max(section_sort_orders)


def test_faq_question_slug_is_unique(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Two questions cannot claim the same anchor, while questions without one are unrestricted."""
    section = FaqSection.insert(title="Sectie", sort_order=1)
    FaqQuestion.insert(section_gid=section.gid, question="Zonder anker A", answer="Antwoord")
    FaqQuestion.insert(section_gid=section.gid, question="Zonder anker B", answer="Antwoord")
    FaqQuestion.insert(section_gid=section.gid, question="Met anker", answer="Antwoord", slug="dubbel-anker")
    db_per_file.commit()

    with pytest.raises(psycopg2.errors.UniqueViolation):
        FaqQuestion.insert(section_gid=section.gid, question="Ook met anker", answer="Antwoord", slug="dubbel-anker")
    db_per_file.rollback()


def test_faq_question_requires_question_text(migrated_db_per_file: None) -> None:
    """The question text is required."""
    assert migrated_db_per_file is None

    row, errors = FaqQuestion.validate_and_insert(answer="Antwoord")

    assert row is None
    assert errors is not None
    assert "question" in errors


def test_parse_faq_seed_converts_answers_to_markdown() -> None:
    """Structured answer blocks become markdown paragraphs and lists."""
    payload = {
        "intro": "Intro",
        "landing_preview_count": 2,
        "categories": [
            {
                "title": "Algemeen",
                "questions": [
                    {
                        "id": "a",
                        "q": "Vraag A",
                        "a": [
                            {"type": "p", "text": "Eerste alinea."},
                            {"type": "p", "text": "Tweede alinea."},
                        ],
                    },
                    {
                        "id": "b",
                        "q": "Vraag B",
                        "a": [{"type": "ul", "items": ["punt 1", "punt 2"]}],
                    },
                ],
            },
            {
                "title": "Thema's",
                "questions": [{"id": "c", "q": "Vraag C", "a": [{"type": "p", "text": "Tekst."}]}],
            },
        ],
    }

    sections = parse_faq_seed(payload)

    assert [section["title"] for section in sections] == ["Algemeen", "Thema's"]
    assert [section["sort_order"] for section in sections] == [1, 2]
    first, second = sections[0]["questions"]
    assert first["answer"] == "Eerste alinea.\n\nTweede alinea."
    assert second["answer"] == "- punt 1\n- punt 2"
    assert sections[1]["questions"][0]["answer"] == "Tekst."


def test_parse_faq_seed_flags_homepage_preview_questions() -> None:
    """Only the first `landing_preview_count` questions are shown on the homepage."""
    payload = {
        "landing_preview_count": 2,
        "categories": [
            {
                "title": "Algemeen",
                "questions": [
                    {"id": "a", "q": "Vraag A", "a": [{"type": "p", "text": "Tekst A."}]},
                    {"id": "b", "q": "Vraag B", "a": [{"type": "p", "text": "Tekst B."}]},
                    {"id": "c", "q": "Vraag C", "a": [{"type": "p", "text": "Tekst C."}]},
                ],
            },
        ],
    }

    sections = parse_faq_seed(payload)

    questions = sections[0]["questions"]
    assert [question["show_on_homepage"] for question in questions] == [True, True, False]
    assert [question["sort_order"] for question in questions] == [1, 2, 3]


def test_markdown_to_text_strips_formatting() -> None:
    """Markdown renders to plain text without tags for search and metadata."""
    assert markdown_to_text("**vet** en [link](https://example.org)") == "vet en link"
    assert markdown_to_text("") == ""
    assert markdown_to_text("<script>alert(1)</script>") == "<script>alert(1)</script>"

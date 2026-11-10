"""Sections and questions for the public FAQ page."""

from typedal import Ref, relationship
from typedal.fields import TextField, TypedField
from typedal.helpers import classproperty

from shared_code.data_model.fields import InternalUUIDField
from shared_code.data_model.tables.base import BaseTable


class FaqSection(BaseTable):
    """One titled group of questions on the public FAQ page."""

    title = TypedField(str, required=True, length=120, label="Sectie")
    sort_order = TypedField(int, label="Volgorde", default=0)

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin page identifier for FAQ sections."""
        return "faq"


class FaqQuestion(BaseTable):
    """One frequently asked question with a markdown answer."""

    section_gid = InternalUUIDField(label="Sectie")
    question = TypedField(str, required=True, length=500, label="Vraag")
    answer = TextField(label="Antwoord")
    show_on_homepage = TypedField(bool, label="Toon op homepage", default=False)
    sort_order = TypedField(int, label="Volgorde", default=0)

    section = relationship(Ref[FaqSection], lambda question, faq_section: question.section_gid == faq_section.gid)

    @classproperty
    def admin_grid(cls) -> str:
        """Return the admin page identifier for FAQ questions."""
        return "faq"

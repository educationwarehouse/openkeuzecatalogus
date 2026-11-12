"""Effective-dated school subject names and their aliases."""

from typedal import TypedField
from typedal.helpers import classproperty

from shared_code.data_model.representers import comma_separated
from shared_code.data_model.tables.base import EffdtTable


class SchoolSubjectEd(EffdtTable):
    """Historical source versions of a school subject and its aliases."""

    name = TypedField(str, length=512, label="Standaardnaam", required=True)
    aliases = TypedField(list[str], label="Aliases", default=list, represent=comma_separated)


class SchoolSubject(SchoolSubjectEd):
    """Current school subject selected from its effective-dated versions."""

    @classproperty
    def admin_grid(cls) -> str:
        """Route generic table-browser links to the subject management grid."""
        return "school-subjects"

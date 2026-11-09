"""Tables for the guided learning-material decision process."""

import datetime as dt
import typing as t

from pydal.validators import IS_IN_SET
from typedal import Ref, TypeDAL, relationship
from typedal.fields import TextField, TypedField
from typedal.types import Validator

from shared_code.data_model.constants import MATERIAL_TYPES, PROCESS_STAGES, PROS_AND_CONS_TYPES
from shared_code.data_model.fields import OptionalUUIDField, UUIDReferenceField
from shared_code.data_model.fields.list_values import possible_list_values
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import BaseTable, EffdtTable
from shared_code.data_model.validators.is_in_set_fixed import IS_IN_SET_FIXED
from shared_code.util.lists import new_list

if t.TYPE_CHECKING:
    from shared_code.data_model import AuthUser, Organisation  # noqa: F401 - used in relationship


class DecisionTeamEd(EffdtTable):
    """A teaching team at an existing school location."""

    location_gid = UUIDReferenceField(label="Vestiging")
    name = TypedField(str, length=255, label="Naam van de vakgroep")
    courses = TypedField(list[str], label="Vakgebieden", default=new_list)
    levels = TypedField(list[str], label="Niveaus", default=new_list)
    years = TypedField(list[str], label="Leerjaren", default=new_list)
    active = TypedField(bool, label="Actief", default=True)

    location = relationship(Ref["Organisation"], lambda self, loc: self.location_gid == loc.gid, label="Vestiging")

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Configure criteria validators after the related catalogue fields exist."""
        from shared_code.data_model import Product

        super().__on_define__(db)
        cls.name.label = "Naam van de Vakgroep"

        cls.courses.requires = t.cast(
            list[Validator],
            [
                IS_IN_SET_FIXED(
                    possible_list_values(Product.subjects, where=Product.available != "verwijderd"), multiple=True
                )
            ],
        )
        cls.levels.requires = t.cast(
            list[Validator],
            [
                IS_IN_SET_FIXED(
                    possible_list_values(Product.levels, where=Product.available != "verwijderd"), multiple=True
                )
            ],
        )
        cls.years.requires = t.cast(
            list[Validator],
            [
                IS_IN_SET_FIXED(
                    possible_list_values(Product.level_x_year, where=Product.available != "verwijderd"), multiple=True
                )
            ],
        )


class DecisionTeam(DecisionTeamEd, SearchMixin, search_fields=("name",)):
    """Current teaching-team model view."""


class DecisionProcess(BaseTable):
    """A staged choice process owned by a teaching team."""

    team_gid = UUIDReferenceField(label="Vakgroep")
    schoolyear = TypedField(str, length=20, label="Schooljaar")
    start_date = TypedField(dt.date, label="Startdatum")
    active = TypedField(bool, label="Actief", default=True)
    process_stage = TypedField(
        str,
        length=10,
        label="Voortgang",
        default="team",
        requires=IS_IN_SET(PROCESS_STAGES),
    )
    courses = TypedField(list[str], label="Vakgebieden", default=new_list)
    levels = TypedField(list[str], label="Niveaus", default=new_list)
    years = TypedField(list[str], label="Leerjaren", default=new_list)
    vision = TextField(label="Visie", default="")
    project_leader_gid = OptionalUUIDField(label="Projectleider")
    reporter_gid = OptionalUUIDField(label="Verslaglegger")
    team_planning = TextField(label="Teamplanning", default="")
    # number of LLM calls spent on this process, capped by AI_QUERY_LIMIT
    ai_usage = TypedField(int, label="Aantal AI queries", default=0)

    team = relationship(Ref[DecisionTeam], lambda self, team: self.team_gid == team.gid)
    theme_visions = relationship(
        list["DecisionThemeVision"],
        lambda self, vision: self.gid == vision.process_gid,
        join="left",
    )


class DecisionProcessNoteEd(EffdtTable):
    """Board or school guidance for one theme, shared by all of that organisation's processes.

    Deliberately *not* scoped to a single process: a board or school sets its kaders and
    adviezen once per theme and every choice process below it inherits them.
    """

    organisation_gid = UUIDReferenceField(label="Organisatie")
    theme = UUIDReferenceField(label="Thema")
    content = TextField(label="Notitie", default="")

    organisation = relationship(Ref["Organisation"], lambda self, org: self.organisation_gid == org.gid)


class DecisionProcessNote(DecisionProcessNoteEd):
    """Current organisation-level guidance-note model view."""


class DecisionMaterialSelection(BaseTable):
    """A material considered during a choice process."""

    process_gid = UUIDReferenceField(label="Keuzeproces")
    name = TypedField(str, length=255, label="Naam")
    olid = TypedField(str | None, length=255, label="OLID")
    material_type = TypedField(str, length=10, requires=IS_IN_SET(MATERIAL_TYPES), default="bought")

    process = relationship(Ref[DecisionProcess], lambda self, process: self.process_gid == process.gid)


class DecisionProsAndCons(BaseTable):
    """One positive or negative assessment attached to a process theme."""

    process_gid = UUIDReferenceField(label="Keuzeproces")
    user_gid = UUIDReferenceField(label="Gebruiker")
    material_selection_gid = OptionalUUIDField(label="Leermiddel")
    item_type = TypedField(str, length=3, requires=IS_IN_SET(PROS_AND_CONS_TYPES))
    theme = OptionalUUIDField(label="Thema")
    content = TextField(label="Toelichting", default="")
    sort_order = TypedField(int, default=0)

    process = relationship(Ref[DecisionProcess], lambda self, process: self.process_gid == process.gid)
    user = relationship(Ref["AuthUser"], lambda self, user: self.user_gid == user.gid)
    material_selection = relationship(
        Ref[DecisionMaterialSelection],
        lambda self, selection: self.material_selection_gid == selection.gid,
    )


class DecisionThemeVision(BaseTable):
    """The team summary for one decision-process theme."""

    process_gid = UUIDReferenceField(label="Keuzeproces")
    theme = UUIDReferenceField(label="Thema")
    summary = TextField(label="Samenvatting", default="")
    sort_order = TypedField(int, default=0)

    process = relationship(Ref[DecisionProcess], lambda self, process: self.process_gid == process.gid)

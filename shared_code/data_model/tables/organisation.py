"""Organisation table definitions."""

import typing as t

from pydal.validators import IS_EMPTY_OR, IS_IN_SET, IS_NOT_EMPTY, IS_URL
from typedal import Ref, TypeDAL, relationship
from typedal.fields import TypedField
from typedal.types import OpRow

from shared_code.data_model.constants import (
    ROLE_BOARD,
    ROLE_LOCATION,
    ROLE_SCHOOL,
    OrganisationType,
)
from shared_code.data_model.constants.organisation import ORG_TYPE_LABELS
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.representers.lists import comma_separated
from shared_code.data_model.tables.base import EffdtTable
from shared_code.data_model.tables.tagged import Predicate, tagged_relationship_query

if t.TYPE_CHECKING:
    # noinspection PyUnusedImports
    from shared_code.data_model import DecisionTeam
    from shared_code.infra.database import DatabaseContext


def keep_organisation_group_in_sync(cls: type[OrganisationEd]) -> t.Callable[[OpRow, int], None]:
    """Keep the organisation RBAC group aligned with the latest active organisation row."""
    db = t.cast("DatabaseContext", cls._db)
    assert db, "Can't use keep_organisation_group_in_sync on a class used without db.define()"
    auth = db.auth
    rbac = auth.raw_rbac

    type_roles: dict[str, str] = {
        OrganisationType.BOARD: ROLE_BOARD,
        OrganisationType.SCHOOL: ROLE_SCHOOL,
        OrganisationType.LOCATION: ROLE_LOCATION,
    }

    def wrapper(_changes: OpRow, row_id: int) -> None:
        row = cls(row_id)
        if not row or row.effstatus is False:
            return

        role = type_roles[row.organisation_type]
        group_email = f"{row.gid}@organisation"

        if existing := rbac.get_group(row.gid):
            rbac.update_identity(existing["object_id"], email=group_email, name=row.name, fullname=row.name)
        else:
            rbac.add_group(
                group_email,
                row.name,
                [role],
                gid=row.gid,
                allow_existing=True,
            )
            db.applog.try_fire(
                {
                    "kind": "event",
                    "action": "organisation-group-created",
                    "user_gid": db.auth.id,
                    "related": row.gid,
                    "details": {
                        "organisation_gid": row.gid,
                        "organisation_name": row.name,
                        "group_email": group_email,
                    },
                },
            )

        rbac.add_permission(row.gid, row.gid, "*")

    return wrapper


class OrganisationEd(EffdtTable):
    """Effective-dated organisation source table."""

    name = TypedField(str, label="Naam", required=True, requires=IS_NOT_EMPTY())
    short_name = TypedField(str | None, label="Korte naam")
    organisation_type = TypedField(
        str,
        label="Type",
        requires=IS_IN_SET({item: ORG_TYPE_LABELS[item] for item in OrganisationType}),
        required=True,
    )
    brin = TypedField(str | None, label="BRIN")
    vestigingscode = TypedField(str | None, label="Vestigingscode")
    email_domains = TypedField(list[str], label="Email Domeinen", represent=comma_separated, public=False)
    website = TypedField(str | None, label="Website", requires=IS_EMPTY_OR(IS_URL()))
    street = TypedField(str | None, label="Straat")
    number = TypedField(str | None, label="Nummer")
    postalcode = TypedField(str | None, label="Postcode")
    city = TypedField(str | None, label="Plaats")

    @classmethod
    def __on_define__(cls, db: TypeDAL) -> None:
        """Register RBAC synchronization once the table is defined."""
        super().__on_define__(db)
        cls.after_insert(keep_organisation_group_in_sync(cls))


class Organisation(
    OrganisationEd,
    SearchMixin,
    search_fields=("name", "short_name", "gid", "brin", "vestigingscode", "city", "postalcode"),
):
    """Current organisation model view."""

    # for boards:
    child_schools = relationship(
        list["Organisation"],
        on=tagged_relationship_query(Predicate.IS_BOARD_OF),
        label="Scholen",
    )
    # for schools:
    parent_board = relationship(
        Ref["Organisation"],
        on=tagged_relationship_query(Predicate.IS_BOARD_OF, inverse=True),
        label="Bestuur",
    )
    child_locations = relationship(
        list["Organisation"], on=tagged_relationship_query(Predicate.IS_SCHOOL_OF), label="Vestigingen"
    )
    # for locations:
    parent_school = relationship(
        Ref["Organisation"], on=tagged_relationship_query(Predicate.IS_SCHOOL_OF, inverse=True), label="School"
    )
    teams = relationship(
        list["DecisionTeam"], lambda org, team: org.gid == team.location_gid, join="left", label="Vakgroepen"
    )

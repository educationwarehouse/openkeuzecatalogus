"""Integration tests for school data-quality report views."""

from typedal import TypeDAL

from shared_code.data_model import OrganisationEd, TaggedEd
from shared_code.data_model.constants import OrganisationType, Predicate


def _reported_location_gids(db: TypeDAL) -> set[str]:
    """Return location gids from the missing-organisation-mapping report."""
    rows = db.executesql("SELECT location_gid FROM locations_without_organisation_mapping_report_v1")
    return {str(row[0]) for row in rows}


def test_mapping_report_includes_location_when_board_organisation_is_removed(db_per_file: TypeDAL) -> None:
    """A surviving relationship must not mask a missing board organisation."""
    board = OrganisationEd.insert(
        name="Report Test Board",
        organisation_type=OrganisationType.BOARD.value,
        email_domains=[],
    )
    school = OrganisationEd.insert(
        name="Report Test School",
        organisation_type=OrganisationType.SCHOOL.value,
        email_domains=[],
    )
    location = OrganisationEd.insert(
        name="Report Test Location",
        organisation_type=OrganisationType.LOCATION.value,
        email_domains=[],
    )
    assert board is not None
    assert school is not None
    assert location is not None

    TaggedEd.insert(
        subject_gid=board.gid,
        predicate=Predicate.IS_BOARD_OF.value,
        object_gid=school.gid,
    )
    TaggedEd.insert(
        subject_gid=school.gid,
        predicate=Predicate.IS_SCHOOL_OF.value,
        object_gid=location.gid,
    )
    db_per_file.commit()

    assert location.gid not in _reported_location_gids(db_per_file)

    OrganisationEd.insert(
        gid=board.gid,
        name=board.name,
        organisation_type=OrganisationType.BOARD.value,
        email_domains=[],
        effstatus=False,
    )
    db_per_file.commit()

    assert location.gid in _reported_location_gids(db_per_file)

"""Expected effects of deleting connected effective-dated records."""

import datetime as dt

from typedal import TypeDAL

from shared_code.data_model import (
    DecisionProcess,
    DecisionTeam,
    DecisionTeamEd,
    Method,
    MethodEd,
    Organisation,
    OrganisationEd,
    Product,
    ProductEd,
    Supplier,
    SupplierEd,
    TaggedEd,
)
from shared_code.data_model.constants import OrganisationType, Predicate
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.organisations import OrganisationBackend
from shared_code.modules.suppliers import SupplierBackend


def test_deleting_school_removes_its_location_from_active_hierarchy(
    migrated_db_per_file: None, db_per_file: TypeDAL
) -> None:
    """A location must not remain active below a deleted school."""
    assert migrated_db_per_file is None

    school = OrganisationEd.insert(name="Deleted school", organisation_type=OrganisationType.SCHOOL.value)
    location = OrganisationEd.insert(name="Child location", organisation_type=OrganisationType.LOCATION.value)
    assert school is not None and location is not None
    TaggedEd.insert(
        subject_gid=school.gid,
        predicate=Predicate.IS_SCHOOL_OF.value,
        object_gid=location.gid,
        last_saved_by="pytest",
    )
    team = DecisionTeamEd.insert(name="Child team", location_gid=location.gid, last_saved_by="pytest")
    assert team is not None
    process = DecisionProcess.insert(
        team_gid=team.gid,
        schoolyear="2026-2027",
        start_date=dt.date.today(),
    )
    assert process is not None

    backend = OrganisationBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("pytest.school-deletion")
    )
    backend.archive_school(school.gid)

    assert not Organisation.where(gid=school.gid).exists()
    assert not Organisation.where(gid=location.gid).exists()
    assert not DecisionTeam.where(gid=team.gid).exists()
    assert DecisionProcess.where(gid=process.gid).first().active is False


def test_deleting_supplier_removes_its_methods_and_products_from_active_catalogue(
    migrated_db_per_file: None, db_per_file: TypeDAL
) -> None:
    """A supplier removal must not leave orphaned active catalogue entries."""
    assert migrated_db_per_file is None

    supplier = SupplierEd.insert(name="Deleted supplier", olid="deleted-supplier")
    assert supplier is not None
    method = MethodEd.insert(
        supplier_gid=supplier.gid,
        olid="deleted-supplier-method",
        name="Supplier method",
        available="leverbaar",
    )
    assert method is not None
    product = ProductEd.insert(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="deleted-supplier-product",
        name="Supplier product",
        available="leverbaar",
    )
    assert product is not None

    backend = SupplierBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("pytest.supplier-deletion")
    )
    backend.archive_supplier(supplier.gid)

    assert not Supplier.where(gid=supplier.gid).exists()
    assert not Method.where(gid=method.gid).exists()
    assert not Product.where(gid=product.gid).exists()


def test_archiving_board_cascades_through_its_school_hierarchy(
    migrated_db_per_file: None, db_per_file: TypeDAL
) -> None:
    """An archived board must not leave its exclusively owned school and location active."""
    assert migrated_db_per_file is None
    board = OrganisationEd.insert(name="Archive board", organisation_type=OrganisationType.BOARD.value)
    school = OrganisationEd.insert(name="Archive board school", organisation_type=OrganisationType.SCHOOL.value)
    location = OrganisationEd.insert(name="Archive board location", organisation_type=OrganisationType.LOCATION.value)
    assert board and school and location
    TaggedEd.insert(
        subject_gid=board.gid,
        predicate=Predicate.IS_BOARD_OF.value,
        object_gid=school.gid,
        last_saved_by="pytest",
    )
    TaggedEd.insert(
        subject_gid=school.gid,
        predicate=Predicate.IS_SCHOOL_OF.value,
        object_gid=location.gid,
        last_saved_by="pytest",
    )
    backend = OrganisationBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("pytest.board-deletion")
    )
    backend.archive_board(board.gid)

    assert not Organisation.where(gid=board.gid).exists()
    assert not Organisation.where(gid=school.gid).exists()
    assert not Organisation.where(gid=location.gid).exists()


def test_archiving_location_and_team_closes_processes(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """A team can be archived directly or through its location without active processes."""
    assert migrated_db_per_file is None
    location = OrganisationEd.insert(name="Archive location", organisation_type=OrganisationType.LOCATION.value)
    assert location
    team = DecisionTeamEd.insert(name="Archive team", location_gid=location.gid, last_saved_by="pytest")
    assert team
    process = DecisionProcess.insert(team_gid=team.gid, schoolyear="2026-2027", start_date=dt.date.today())
    assert process
    backend = OrganisationBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("pytest.location-deletion")
    )
    backend.archive_team(team.gid)
    assert not DecisionTeam.where(gid=team.gid).exists()
    assert DecisionProcess.where(gid=process.gid).first().active is False
    assert Organisation.where(gid=location.gid).exists()

    second_team = DecisionTeamEd.insert(name="Second team", location_gid=location.gid, last_saved_by="pytest")
    assert second_team
    backend.archive_location(location.gid)
    assert not Organisation.where(gid=location.gid).exists()
    assert not DecisionTeam.where(gid=second_team.gid).exists()


def test_archiving_method_cascades_products_but_product_archive_keeps_parent(
    migrated_db_per_file: None, db_per_file: TypeDAL
) -> None:
    """Catalogue deletion cascades downwards only."""
    assert migrated_db_per_file is None
    supplier = SupplierEd.insert(name="Archive method supplier", olid="archive-method-supplier")
    assert supplier
    method = MethodEd.insert(
        supplier_gid=supplier.gid, olid="archive-method", name="Archive method", available="leverbaar"
    )
    assert method
    first = ProductEd.insert(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="archive-method-product-1",
        name="First product",
        available="leverbaar",
    )
    second = ProductEd.insert(
        supplier_gid=supplier.gid,
        method_gid=method.gid,
        olid="archive-method-product-2",
        name="Second product",
        available="leverbaar",
    )
    assert first and second
    backend = SupplierBackend.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("pytest.method-deletion")
    )
    backend.archive_product(first.gid)
    assert not Product.where(gid=first.gid).exists()
    assert Method.where(gid=method.gid).exists()
    assert Supplier.where(gid=supplier.gid).exists()

    backend.archive_method(method.gid)
    assert not Product.where(gid=second.gid).exists()
    assert not Method.where(gid=method.gid).exists()
    assert Supplier.where(gid=supplier.gid).exists()

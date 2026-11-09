"""Integration coverage for the location product-usage reporting view."""

import typing as t

from shared_code.data_model import AuthUser, LocationProductUsageReport
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.decision_processes import DecisionProcessBackend
from shared_code.util.olid import generate as generate_olid

VESTIGING_CENTRUM_GID = "db1e5f11-b1d0-4ca2-b350-57e089fe159d"


def _backend(
    db: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> DecisionProcessBackend:
    """Build the decision-process backend used to seed report rows."""
    return DecisionProcessBackend.with_injected(db=db, auth_adapter=auth_adapter_factory(admin_user))


def test_location_product_usage_report_aggregates_products_across_processes(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
) -> None:
    """One product row combines its teams, school years, and active/archive process counts."""
    backend = _backend(db_per_file, admin_user, auth_adapter_factory)
    first_team = backend.create_team(VESTIGING_CENTRUM_GID, "Vakgroep Nederlands")
    second_team = backend.create_team(VESTIGING_CENTRUM_GID, "Vakgroep Engels")
    active_process = backend.create_process(first_team.gid, "2026-2027")
    archived_process = backend.create_process(second_team.gid, "2025-2026")

    product_olid = generate_olid("product", "isbn:9780000000001")
    backend.change_material_selection(active_process.gid, "add", "bought", "Rekenrijk", product_olid)
    backend.change_material_selection(archived_process.gid, "add", "bought", "Rekenrijk", product_olid)
    backend.archive_process(archived_process.gid)

    rows = LocationProductUsageReport.where(LocationProductUsageReport.location_gid == VESTIGING_CENTRUM_GID).collect()

    assert len(rows) == 1
    row = rows.first()
    assert row.product_name == "Rekenrijk"
    assert row.product_olid == product_olid
    assert set(row.team_names) == {"Vakgroep Nederlands", "Vakgroep Engels"}
    assert set(row.schoolyears) == {"2025-2026", "2026-2027"}
    assert row.active_process_count == 1
    assert row.archived_process_count == 1
    assert row.process_count == 2

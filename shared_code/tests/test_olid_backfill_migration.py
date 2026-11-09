"""Integration tests for the collision-resistant method OLID backfill."""

import datetime as dt
import hashlib
import logging
import uuid

import pytest
from typedal import TypeDAL

from shared_code.data_model import (
    DecisionMaterialSelection,
    DecisionProcess,
    DecisionTeamEd,
    Method,
    MethodEd,
    SupplierEd,
)
from shared_code.migrations.migration_support.olid import backfill_collision_resistant_olids_v1
from shared_code.util.olid import generate, generate_supplier_olid


def _legacy_method_olid(key: str) -> str:
    """Return the OLID that the generator produced before hashing the original key."""
    identifier = generate("method", key).rpartition("#")[0]
    return identifier + "#" + hashlib.shake_256(identifier.encode()).hexdigest(2)


def _supplier(name: str) -> SupplierEd:
    gid = str(uuid.uuid4())
    supplier = SupplierEd.insert(
        gid=gid,
        name=name,
        olid=generate_supplier_olid(gid),
        email_domains=[f"{uuid.uuid4().hex}.example.test"],
        endpoint_type="none",
        status_visions="compleet",
    )
    assert supplier is not None
    return supplier


def _selection(olid: str) -> DecisionMaterialSelection:
    team = DecisionTeamEd.insert(name="Backfill team", location_gid=str(uuid.uuid4()), last_saved_by="pytest")
    assert team is not None

    process = DecisionProcess.insert(team_gid=team.gid, schoolyear="2026-2027", start_date=dt.date.today())
    assert process is not None

    selection = DecisionMaterialSelection.insert(process_gid=process.gid, name="Selected method", olid=olid)
    assert selection is not None
    return selection


def test_backfill_upgrades_reconstructable_method_olids(migrated_db_per_file: None, db_per_file: TypeDAL) -> None:
    """Methods whose source key is known get the new OLID while keeping their GID, history and selections."""
    assert migrated_db_per_file is None
    publisher = f"Backfill Publisher {uuid.uuid4().hex[:8]}"
    key = f"{publisher.lower()}:rekenen & taal"
    legacy_olid = _legacy_method_olid(key)
    new_olid = generate("method", key)
    assert legacy_olid != new_olid

    supplier = _supplier(publisher)
    method = MethodEd.insert(supplier_gid=supplier.gid, olid=legacy_olid, name="Rekenen & Taal")
    assert method is not None
    selection = _selection(legacy_olid)
    db_per_file.commit()

    backfill_collision_resistant_olids_v1(db_per_file)
    db_per_file.commit()

    assert Method.where(Method.olid == new_olid).first_or_fail().gid == method.gid
    assert not Method.where(Method.olid == legacy_olid).exists()
    assert MethodEd.where(MethodEd.gid == method.gid, MethodEd.olid == legacy_olid).exists()
    assert DecisionMaterialSelection.where(id=selection.id).first_or_fail().olid == new_olid


def test_backfill_preserves_method_olids_without_source_key(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Methods whose source key cannot be reconstructed keep their OLID and are reported."""
    assert migrated_db_per_file is None
    publisher = f"Unknown Publisher {uuid.uuid4().hex[:8]}"
    legacy_olid = _legacy_method_olid(f"{publisher.lower()}:verdwenen familie")

    supplier = _supplier(f"Other Supplier {uuid.uuid4().hex[:8]}")
    method = MethodEd.insert(supplier_gid=supplier.gid, olid=legacy_olid, name="Hernoemde methode")
    assert method is not None
    selection = _selection(legacy_olid)
    db_per_file.commit()

    with caplog.at_level(logging.WARNING, logger="shared_code.migrations.migration_support.olid"):
        backfill_collision_resistant_olids_v1(db_per_file)
    db_per_file.commit()

    assert Method.where(Method.olid == legacy_olid).first_or_fail().gid == method.gid
    assert DecisionMaterialSelection.where(id=selection.id).first_or_fail().olid == legacy_olid
    assert any(legacy_olid in record.getMessage() for record in caplog.records)

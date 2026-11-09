"""Tests for creating suppliers from cached Kennisnet publishers."""

import inspect
import uuid
from pathlib import Path

import pytest
from apps.admin.controllers.kennisnet import save_kennisnet_supplier_configurations
from common.models import auth
from ombott.request_pkg.helpers import FormsDict
from py4web.core import Fixture

from py4web import HTTP, request, response
from shared_code.data_model import Supplier
from shared_code.modules.scrapers.kennisnet_catalogue import KennisnetCataloguePublisher, _catalogue_database


def _set_request_forms(values: dict[str, str]) -> None:
    """Set parsed form values for an unwrapped admin action."""
    request.environ["ombott.request.forms"] = FormsDict(values)


def _run_supplier_configuration() -> HTTP:
    """Run the action body and return its redirect response."""
    auth.flash.on_request({})
    try:
        with pytest.raises(HTTP) as redirect:
            inspect.unwrap(save_kennisnet_supplier_configurations)()
        return redirect.value
    finally:
        Fixture.local_delete(auth.flash)


def test_save_kennisnet_supplier_configurations_creates_selected_supplier(
    admin_app_request_context: None,
    tmp_path: Path,
) -> None:
    """A selected unconfigured publisher becomes an Edu-V Kennisnet supplier."""
    catalogue_db = _catalogue_database(database_path=tmp_path / "kennisnet-catalogue.sqlite")
    publisher_name = f"Pytest publisher {uuid.uuid4().hex}"
    publisher = KennisnetCataloguePublisher.insert(publisher=publisher_name, version="v2")
    catalogue_db.commit()
    _set_request_forms({f"publisher_gid_{publisher.gid}": publisher.gid})

    redirect = _run_supplier_configuration()

    supplier = Supplier.where(Supplier.name == publisher_name).first()
    assert redirect.status == 303
    assert supplier
    assert supplier.endpoint_type == "edu-v-kennisnet-v2"
    assert supplier.endpoint_publisher == publisher_name


def test_save_kennisnet_supplier_configurations_requires_selection(admin_app_request_context: None) -> None:
    """Submitting the bulk form without a publisher returns to the publisher grid."""
    _set_request_forms({})

    redirect = _run_supplier_configuration()

    assert redirect.status == 303
    assert response.headers["Location"].endswith("kennisnet-catalogue/suppliers")


def test_save_kennisnet_supplier_configurations_rejects_missing_publisher(admin_app_request_context: None) -> None:
    """A stale bulk-form selection returns to the publisher grid with a warning."""
    _set_request_forms({"publisher_gid_missing": "missing"})

    redirect = _run_supplier_configuration()

    assert redirect.status == 303
    assert response.headers["Location"].endswith("kennisnet-catalogue/suppliers")

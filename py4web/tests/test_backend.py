"""Tests for Endow-backed py4web service wiring."""

from common.models import auth, backend

from shared_code.services import Applogger, EntreeOAuthService, Mailer


def test_py4web_backend_supplies_shared_service_instances() -> None:
    """Py4web should consume service instances from one backend graph."""
    assert isinstance(backend.mailer, Mailer)
    assert isinstance(backend.applog, Applogger)
    assert isinstance(backend.entree_oauth, EntreeOAuthService)
    assert backend.entree_oauth.applog is backend.applog
    assert auth.sender is backend.mailer

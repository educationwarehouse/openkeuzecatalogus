"""Tests for Entree OAuth services."""

import typing as t

from typedal import TypeDAL

from shared_code.services.entree import MockEntreeOAuthService, RequestsEntreeOAuthService
from shared_code.services.entree.contracts import EntreeOAuthService

if t.TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_mock_entree_service_exposes_configured_payloads() -> None:
    """Mock service should return configured token and userinfo responses."""
    service = MockEntreeOAuthService.from_env()
    service.token_response = {"access_token": "fake-token"}
    service.userinfo_response = {"uid": "test-user", "sn": "Jansen"}

    token = service.exchange_code_for_token(
        token_url="https://example.test/token",
        code="abc",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://example.test/callback",
    )
    userinfo = service.fetch_userinfo(userinfo_url="https://example.test/userinfo", token="fake-token")

    assert token == "fake-token"
    assert userinfo == {"uid": "test-user", "sn": "Jansen"}


def test_normalize_userinfo_combines_infix_and_prefixes_email(db_psql: TypeDAL) -> None:
    """Service should map Entree names/email and include hashed password."""
    service = RequestsEntreeOAuthService.with_injected(db=db_psql)

    user = service.normalize_userinfo(
        {
            "uid": "jdoe",
            "sn": "Veen",
            "nlEduPersonTussenvoegsels": "van der",
        },
    )

    assert user is not None
    assert user["last_name"] == "van der Veen"
    assert user["email"] == "kennisnet:jdoe"
    assert user["password"]  # (Lazy)Crypt obj


def test_normalize_userinfo_without_mail_or_uid_returns_none(db_psql: TypeDAL) -> None:
    """Missing identity should stop user creation."""
    service = RequestsEntreeOAuthService.with_injected(db=db_psql)

    user = service.normalize_userinfo({"sn": "NoEmail"})

    assert user is None


def test_entree_service_from_env_uses_mock_when_enabled(monkeypatch: MonkeyPatch) -> None:
    """`ENTREE_FAKE=1` should route to the fake implementation."""
    monkeypatch.setenv("ENTREE_FAKE", "1")
    service = EntreeOAuthService.from_env()
    assert isinstance(service, MockEntreeOAuthService)

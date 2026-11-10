"""Fake Entree OAuth implementation for tests."""

import os
import typing as t

from ...data_model import AnyDict
from .contracts import EntreeOAuthService

MOCK_EMAIL_DOMAIN = os.environ.get("PYTEST_MOCK_EMAIL_DOMAIN", "")


class MockEntreeOAuthService(EntreeOAuthService):
    """Configurable fake Entree OAuth service used in tests."""

    def __init__(
        self,
        token_response: AnyDict | None = None,
        userinfo_response: AnyDict | None = None,
    ) -> None:
        """Initialize fake responses for token and userinfo endpoints."""
        super().__init__()

        self.token_response = token_response or {"access_token": "fake-entree-access-token"}
        self.userinfo_response = userinfo_response or {
            "sub": "mock-entree-subject",
            "uid": f"mock-entree-user@{MOCK_EMAIL_DOMAIN}",
            "mail": f"mock-entree-user@{MOCK_EMAIL_DOMAIN}",
            "givenName": "Mock",
            "sn": "Entree",
        }

    @classmethod
    def from_env(cls) -> MockEntreeOAuthService:
        """Build a fake service instance from environment selection only."""
        return cls()

    def exchange_code_for_token(
        self,
        token_url: str,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> str | None:
        """Return the configured access token from the fake token payload."""
        return t.cast(str | None, self.token_response.get("access_token"))

    def fetch_userinfo(self, userinfo_url: str, token: str) -> AnyDict:
        """Return a copy of the configured fake userinfo payload."""
        return dict(self.userinfo_response)

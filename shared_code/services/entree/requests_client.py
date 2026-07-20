"""Requests-based Entree OAuth implementation."""

import typing as t

import requests

from .contracts import EntreeOAuthService


class RequestsEntreeOAuthService(EntreeOAuthService):
    """Entree OAuth service using requests for transport."""

    def __init__(self, http_client: requests.Session | None = None, timeout_seconds: int = 10) -> None:
        """Initialize HTTP transport and request timeout settings."""
        super().__init__()

        self.http_client = http_client or requests.Session()
        self.timeout_seconds = timeout_seconds

    def exchange_code_for_token(
        self,
        token_url: str,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> str | None:
        """Exchange an authorization code for an access token."""
        post_data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        headers = {"Accept": "application/json"}
        resp = self.http_client.post(
            token_url,
            data=post_data,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        output = resp.json()
        return t.cast(str | None, output.get("access_token"))

    @classmethod
    def from_env(cls) -> EntreeOAuthService:
        """Build a requests-backed service from environment defaults."""
        return cls()

    def fetch_userinfo(self, userinfo_url: str, token: str) -> dict[str, t.Any]:
        """Fetch user profile data from the Entree userinfo endpoint."""
        resp = self.http_client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        return resp.json()

"""Kennisnet Entree OAuth service contracts."""

import abc
import secrets
import typing as t

from endow import Service
from pydal.validators import CRYPT

from shared_code.services.applog import Applogger
from shared_code.util.env import bool_from_env


class EntreeOAuthService(Service, abc.ABC):
    """Service contract for Entree OAuth2 exchange and profile mapping."""

    applog: Applogger

    @abc.abstractmethod
    def exchange_code_for_token(
        self,
        token_url: str,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> str | None:
        """Exchange an authorization code for an access token."""
        ...

    @abc.abstractmethod
    def fetch_userinfo(self, userinfo_url: str, token: str) -> dict[str, t.Any]:
        """Fetch user profile payload from Entree userinfo endpoint."""
        ...

    def fetch_normalized_userinfo(self, userinfo_url: str, token: str) -> dict[str, t.Any] | None:
        """Fetch Entree user info and return normalized auth-plugin user fields."""
        user_info = self.fetch_userinfo(userinfo_url=userinfo_url, token=token)
        return self.normalize_userinfo(user_info)

    @classmethod
    def from_env(cls) -> EntreeOAuthService:
        """Instantiate the configured Entree OAuth service from environment variables."""
        if bool_from_env("ENTREE_FAKE", False):
            from .fake import MockEntreeOAuthService

            return MockEntreeOAuthService.from_env()
        else:
            from .requests_client import RequestsEntreeOAuthService

            return RequestsEntreeOAuthService.from_env()

    def normalize_userinfo(self, user_info: dict[str, t.Any]) -> dict[str, t.Any] | None:
        """Map Entree user info to auth plugin user fields."""
        user_info = dict(user_info)

        last_name = t.cast(str, user_info.get("sn", ""))
        if infix := user_info.get("nlEduPersonTussenvoegsels"):
            user_info["last_name"] = f"{infix} {last_name}"
        else:
            user_info["last_name"] = last_name

        email = user_info.get("mail") or user_info.get("uid")
        if not email:
            return None
        user_info["email"] = f"kennisnet:{email}"

        # Emit an explicit Entree login marker when identity normalization succeeds.
        self.applog.log_auth_action(
            action="login",
            success=True,
            email=user_info["email"],
        )

        password = secrets.token_urlsafe(32)
        user_info["password"] = CRYPT()(password)[0]

        return user_info

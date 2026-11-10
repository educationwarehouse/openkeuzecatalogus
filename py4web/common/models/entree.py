"""Entree OAuth plugin wiring for the py4web app."""

import secrets
import typing as t
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from py4web.utils.auth import Auth
from py4web.utils.auth_plugins import OAuth2

from py4web import HTTP, URL, redirect, request
from shared_code.infra.web import PY4WEB_URL
from shared_code.services.entree import EntreeOAuthService

from .. import settings

if t.TYPE_CHECKING:
    from .backend.auth_cls import AppAuth


class EntreeLoginError(HTTP):
    """Rejected Entree callback with a non-sensitive audit reason."""

    def __init__(self, reason: str) -> None:
        """Keep provider credentials and payloads out of callback errors."""
        self.reason = reason
        super().__init__(401, "Entree-login mislukt. Probeer opnieuw in te loggen.")


class OAuth2Kennisnet(OAuth2):
    """OAuth2 plugin adapter for the Kennisnet Entree provider."""

    name = "oauth2kennisnet"
    label = "Kennisnet Entree"
    default_scope = "openid profile email"
    maps = {
        "email": "email",
        "sso_id": "sub",
        "first_name": "givenName",
        "last_name": "last_name",
        "password": "password",
    }

    def __init__(
        self,
        service: EntreeOAuthService,
        endpoint: str,
        client_id: str,
        client_secret: str,
        callback_url: str = "auth/plugin/oauth2kennisnet/callback",
        scope: str | None = None,
        scheme: bool = True,
        passed_state: str | None = None,
    ) -> None:
        """Configure the Entree endpoints and HTTP service helper."""
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            callback_url=callback_url,
            scope=scope,
            scheme=scheme,
            passed_state=passed_state,
        )
        self.login_url = f"https://{endpoint}/oidc/authorize"
        self.token_url = f"https://{endpoint}/oidc/token"
        self.userinfo_url = f"https://{endpoint}/oidc/userinfo"
        self.service = service

    def callback(self, query: dict) -> dict | None:
        """Exchange the callback code for a normalized user profile."""
        code = query.get("code")
        if not code:
            raise EntreeLoginError("missing-code")

        token = self.service.exchange_code_for_token(
            token_url=self.token_url,
            code=code,
            client_id=str(client_id) if (client_id := self.parameters.get("client_id")) else "",
            client_secret=str(secret) if (secret := self.parameters.get("client_secret")) else "",
            redirect_uri=URL(self.parameters.get("callback_url"), scheme=self.parameters.get("scheme")),
        )
        if not token:
            raise EntreeLoginError("token-exchange-failed")

        profile = self.service.fetch_normalized_userinfo(userinfo_url=self.userinfo_url, token=token)
        if not profile:
            raise EntreeLoginError("invalid-profile")
        return profile

    def _handle_callback(self, auth: AppAuth, get_vars: dict) -> None:
        """Cover the plugin callback, which bypasses the framework's form events."""
        try:
            super()._handle_callback(auth, get_vars)
        except HTTP as result:
            success = 300 <= result.status < 400 and bool(auth.get_user())
            user = auth.get_user() if success else None
            auth.form_source.log_auth_action(
                action="login",
                success=success,
                user=user.as_dict() if user else None,
                details={
                    "provider": self.name,
                    "reason": "authenticated" if success else getattr(result, "reason", "authentication-rejected"),
                },
            )
            raise
        except Exception:
            auth.form_source.log_auth_action(
                action="login", success=False, details={"provider": self.name, "reason": "callback-error"}
            )
            raise

    def _login_url_with_state(self, auth: AppAuth) -> str:
        """Bind the provider redirect to a fresh state in this session."""
        state = secrets.token_urlsafe(32)
        auth.session["entree_oauth_state"] = state

        parts = urlsplit(self.get_login_url())
        query = dict(parse_qsl(parts.query))
        query["state"] = state

        return urlunsplit(parts._replace(query=urlencode(query)))

    def _validate_callback_state(self, auth: AppAuth, get_vars: dict[str, t.Any]) -> None:
        """Consume and verify the state before exchanging the callback code."""
        expected_state = auth.session.pop("entree_oauth_state", None)
        received_state = get_vars.get("state")

        if (
            isinstance(expected_state, str)
            and isinstance(received_state, str)
            and received_state.isascii()
            and secrets.compare_digest(expected_state, received_state)
        ):
            return

        auth.form_source.log_auth_action(
            action="login", success=False, details={"provider": self.name, "reason": "invalid-state"}
        )
        raise HTTP(400, "Ongeldige of verlopen OAuth-login. Probeer opnieuw in te loggen.")

    def handle_request(self, auth: AppAuth, path: str, get_vars: dict, post_vars: dict) -> None:
        """Preserve explicit next targets while leaving the default redirect role-aware."""
        if path == "login":
            if next_url := request.query.get("next"):
                auth.session["_next"] = next_url
            else:
                auth.session.pop("_next", None)

            return redirect(self._login_url_with_state(auth))

        if path == "callback":
            self._validate_callback_state(auth, get_vars)

        return super().handle_request(auth, path, get_vars, post_vars)


def setup_entree_plugin(service: EntreeOAuthService, auth: Auth) -> None:
    """Register the Entree plugin on the shared auth instance."""
    entree_endpoint = settings.ENTREE_CLIENT_ENDPOINT

    entree_client_id = settings.ENTREE_CLIENT_ID or "fake-entree-client-id"
    entree_client_secret = settings.ENTREE_CLIENT_SECRET or "fake-entree-client-secret"

    entree_plugin = OAuth2Kennisnet(
        service,
        endpoint=entree_endpoint,
        client_id=entree_client_id,
        client_secret=entree_client_secret,
    )
    if settings.ENTREE_FAKE:
        entree_plugin.login_url = entree_endpoint or PY4WEB_URL("auth/entree_mock_authorize")

    auth.register_plugin(entree_plugin)

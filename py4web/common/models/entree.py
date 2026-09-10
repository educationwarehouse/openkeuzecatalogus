"""Entree OAuth plugin wiring for the py4web app."""

from py4web.utils.auth import Auth
from py4web.utils.auth_plugins import OAuth2

from py4web import URL, redirect, request
from shared_code.infra.web import PY4WEB_URL
from shared_code.services.entree import EntreeOAuthService

from .. import settings


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
        statecheck = query.get("state")
        if not code:
            return None

        passed_state = self.parameters.get("passed_state")
        if passed_state is not None and statecheck != passed_state:
            return None

        token = self.service.exchange_code_for_token(
            token_url=self.token_url,
            code=code,
            client_id=str(client_id) if (client_id := self.parameters.get("client_id")) else "",
            client_secret=str(secret) if (secret := self.parameters.get("client_secret")) else "",
            redirect_uri=URL(self.parameters.get("callback_url"), scheme=self.parameters.get("scheme")),
        )
        if not token:
            return None

        return self.service.fetch_normalized_userinfo(userinfo_url=self.userinfo_url, token=token)

    def handle_request(self, auth: Auth, path: str, get_vars: dict, post_vars: dict) -> None:
        """Preserve explicit next targets while leaving the default redirect role-aware."""
        if path == "login":
            if next_url := request.query.get("next"):
                auth.session["_next"] = next_url
            else:
                auth.session.pop("_next", None)

            return redirect(self.get_login_url())

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

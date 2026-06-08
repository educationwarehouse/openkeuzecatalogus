import typing as t

from py4web.utils.auth import Auth, DefaultAuthForms
from py4web.utils.form import Form, FormStyleBootstrap5
from pydal.objects import Row
from redis import Redis
from typedal.types import Query

from py4web import URL, Session, redirect, request
from shared_code.data_model.tables import AuthUser
from shared_code.modules.auth import (
    mark_reset_password_expiry,
    validate_reset_password_token,
)
from shared_code.modules.auth.password_reset import RESET_PASSWORD_LINK_MAX_AGE_HOURS
from shared_code.services import Applogger, Mailer

from .. import settings
from .common import db
from .entree import setup_entree_plugin

redis = Redis(host="redis-master", port=6379)

session = Session(secret=settings.SESSION_SECRET, storage=redis, name="shared_session")


ALLOWED_ACTIONS = [
    "login",
    "logout",
    "request_reset_password",
    "reset_password",
    "change_password",
    # "change_email",
    "profile",
    # "config",
    "register",
    "verify_email",
    # "unsubscribe",
]


class LoggingAuthForms(DefaultAuthForms):
    _LOGIN_REDIRECT_ACTIONS: t.ClassVar[set[str]] = {
        "register",
        "request_reset_password",
        "reset_password",
    }

    def __init__(self, _auth: Auth, applogger: Applogger | None = None) -> None:
        super().__init__(_auth)
        self._applogger = applogger or Applogger.from_env()

    @t.overload
    def logout(self, model: t.Literal[True]) -> dict[str, t.Any]: ...

    @t.overload
    def logout(self, model: t.Literal[False]) -> str: ...

    def logout(self, model: bool = False) -> dict[str, t.Any] | str:  # ty: ignore[invalid-method-override]
        user = auth.get_user()
        self.log_auth_action(action="logout", success=True, user=user)
        return super().logout(model=model)

    def _postprocessing(self, action: str, form: Form | None = None, user: Row | None = None) -> None:
        if action == "logout":
            # already logged
            return

        success = bool(form.accepted) if form else True
        self.log_auth_action(action=action, success=success, user=user)

        if action in self.auth.on_accept:
            self.auth.on_accept[action](form, user)

        if not form or form.accepted:
            next_page = self.auth.session.get(f"_next_{action}") or (
                URL("auth", "login") if self._LOGIN_REDIRECT_ACTIONS else URL("index")
            )

            raise redirect(next_page)

    def log_auth_action(
        self,
        action: str,
        success: bool,
        user: dict[str, t.Any] | Row | None = None,
        email: str | None = None,
    ) -> None:
        user = user or {}
        self._applogger.log_auth_action(
            action=action,
            user_gid=user.get("gid"),
            email=email or user.get("email"),
            success=success,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )


class AppAuth(Auth):
    """Auth adapter that emits applog events for selected auth actions."""

    form_source: LoggingAuthForms

    FLASH_MESSAGES: t.ClassVar[dict[str, str]] = {
        "link-expired": "Deze link is verlopen.",
    }

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.form_source = LoggingAuthForms(self)

    def login(self, email: str, password: str) -> tuple[Row, None] | tuple[None, str]:
        user, error = super().login(email, password)
        if user:
            self.form_source.log_auth_action("login", success=True, user=user, email=email)
        else:
            self.form_source.log_auth_action("invalid_login_attempt", success=False, email=email)
        return user, error

    def _flash_message_text(self, key: str) -> str:
        return self.FLASH_MESSAGES.get(key, key)

    def flash_message(self, key: str, class_name: str = "alert-info") -> None:
        self.flash.set(self._flash_message_text(key), class_name)

    def flash_error(self, key: str) -> None:
        self.flash_message(key, "alert-danger")

    def flash_warning(self, key: str) -> None:
        self.flash_message(key, "alert-warning")

    def flash_success(self, key: str) -> None:
        self.flash_message(key, "alert-success")

    def flash_info(self, key: str) -> None:
        self.flash_message(key, "alert-info")

    def _query_from_token(self, token: str) -> Query:
        user_id, error = validate_reset_password_token(token)

        if error:
            # reset token expired
            self.flash_error(error)
            return redirect(URL("auth/request_reset_password"))
        elif user_id:
            # user valid reset token
            return AuthUser.id == user_id
        else:
            # fallback; different type of action token
            return super()._query_from_token(token)

    def request_reset_password(
        self,
        email: str,
        send: bool = True,
        next: str = "",
        route: str | None = None,
    ) -> str | None:
        token = super().request_reset_password(email, send=send, next=next, route=route)
        if token:
            mark_reset_password_expiry(token)
        return token


auth = AppAuth(session, db, define_tables=False)
auth.use_username = False
auth.param.registration_requires_confirmation = True
auth.param.registration_requires_approval = False
auth.param.login_after_registration = False
auth.param.allowed_actions = ALLOWED_ACTIONS
auth.param.login_expiration_time = 3600
auth.param.password_complexity = {"entropy": 50}
auth.param.block_previous_password_num = 3
auth.param.default_login_enabled = True


auth.param.messages["verify_email"] = {  # type: ignore
    "subject": "Bevestig je e-mailadres",
    "body": "Hallo {first_name}, klik {link} om je e-mailadres te bevestigen.",
}
auth.param.messages["reset_password"] = {  # type: ignore
    "subject": "Wachtwoord opnieuw instellen",
    "body": (
        "Hallo {first_name}, klik {link} om je wachtwoord opnieuw in te stellen. "
        f"Deze link is slechts {RESET_PASSWORD_LINK_MAX_AGE_HOURS} uur geldig."
    ),
}
auth.param.messages["labels"].update(  # type: ignore
    {
        "password": "Wachtwoord",
        "password_again": "Wachtwoord (nogmaals)",
        "username_or_email": "Gebruikersnaam of e-mailadres",
    }
)
auth.param.messages["buttons"].update(  # type: ignore
    {
        "lost-password": "Wachtwoord vergeten",
        "register": "Registreren",
        "request": "Versturen",
        "sign-in": "Inloggen",
        "sign-up": "Registreren",
    }
)

production_entree = settings.ENTREE_CLIENT_ENDPOINT and settings.ENTREE_CLIENT_ID and settings.ENTREE_CLIENT_SECRET

if settings.ENTREE_FAKE or production_entree:
    setup_entree_plugin(auth)

auth.param.formstyle = FormStyleBootstrap5

auth.fix_actions()

auth.sender = Mailer.from_env(db)

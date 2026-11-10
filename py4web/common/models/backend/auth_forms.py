"""Auth form hooks with applog integration."""

import typing as t

from py4web.utils.auth import DefaultAuthForms
from py4web.utils.form import Form
from pydal.objects import Row
from yatl import CAT, DIV
from yatl.helpers import A

from common.models.redirects import find_next
from py4web import URL, redirect, request
from shared_code.data_model import AnyDict
from shared_code.data_model.constants import ROLE_SUPPLIER
from shared_code.data_model.tables import AuthUser
from shared_code.data_model.validators.is_existing_sso_account import (
    SSO_REGISTERED_ACCOUNT_ERROR,
    build_normalized_email_match_query,
)
from shared_code.services import Applogger
from shared_code.util.email import normalize_email_for_lookup

if t.TYPE_CHECKING:
    from common.models.backend.auth_cls import AppAuth


class LoggingAuthForms(DefaultAuthForms):
    """Auth form hooks that write auth activity to the applogger."""

    _LOGIN_SSO_ACCOUNT_HINT_ERROR: t.ClassVar[str] = "sso-login-account"

    no_forms = [*DefaultAuthForms.no_forms, "request_magic_login", "magic_login"]

    _LOGIN_REDIRECT_ACTIONS: t.ClassVar[set[str]] = {
        "register",
        "request_magic_login",
        "request_reset_password",
        "reset_password",
    }

    def __init__(self, _auth: AppAuth, applog: Applogger) -> None:
        """Initialise the form hooks with an auth instance and logger."""
        super().__init__(_auth)
        self.applog = applog

    def _redirect_target_for_authenticated_user(self) -> str:
        """Send authenticated users to their landing page instead of the login form."""
        if self.auth.auth_context.is_admin() or self.auth.auth_context.has_membership(ROLE_SUPPLIER):
            default = URL("admin", "index", use_appname=False)
        else:
            default = URL("index", use_appname=False)

        return find_next(default)

    @t.overload
    def logout(self, model: t.Literal[True]) -> AnyDict: ...

    @t.overload
    def logout(self, model: t.Literal[False]) -> str: ...

    def logout(self, model: bool = False) -> AnyDict | str:  # ty: ignore[invalid-method-override]
        """Log logout attempts before delegating to the base implementation."""
        user = self.auth.get_user()
        self.log_auth_action(action="logout", success=True, user=user.as_dict() if user else {})
        return super().logout(model=model)

    def login(self, model: bool = False) -> AnyDict | str | Form:
        """Skip the login form when the user already has a valid session."""
        if not model and self.auth.is_logged_in:
            raise redirect(self._redirect_target_for_authenticated_user())

        result = super().login(model=model)

        if not isinstance(result, Form):
            return result

        # note
        #  py4web 1.20260403 has an issue where it returns too early if the form has an error,
        #  which results in the other buttons (oauth, register, ...) not showing up.
        #  we solve this by redirecting from POST to GET; storing the entered email and error in session

        if result.submitted and not result.accepted:
            entered_email = str(result.vars.get("email") or "").strip()
            if (
                entered_email
                and self._is_invalid_login_error(result.errors)
                and self._has_existing_sso_account(entered_email)
            ):
                result.errors["password"] = self._LOGIN_SSO_ACCOUNT_HINT_ERROR

            old = result.vars
            old.pop("password", None)
            self.auth.session["login-error"] = (old, result.errors)
            self.auth.session.save()
            return redirect(request.url)

        if old_and_errors := self.auth.session.pop("login-error", None):
            result.cached_helper = (
                None  # clear cache (prebuilt form html), otherwise the errors and old values don't show up
            )

            result.vars, result.errors = old_and_errors
            self._replace_login_sso_hint_with_magic_link(result.errors, email=str(result.vars.get("email") or ""))

            top_buttons = self.login_buttons()  # rebuild oauth plugin buttons
            result.structure.insert(0, DIV(top_buttons["combined_div"]))

        return result

    def _is_invalid_login_error(self, errors: AnyDict) -> bool:
        """Return whether form errors represent generic invalid credentials."""
        password_error = str(errors.get("password") or "").strip().lower()
        return password_error in {
            "invalid credentials",
            "invalid_credentials",
            "ongeldige inloggegevens.",
        }

    def _has_existing_sso_account(self, email: str) -> bool:
        """Return whether the entered login email belongs to an existing SSO account."""
        normalized_email = normalize_email_for_lookup(email)
        query = (AuthUser.sso_id != None) & build_normalized_email_match_query(AuthUser.email, normalized_email)
        return bool(AuthUser.where(query).select(AuthUser.id, limitby=(0, 1)).first())

    def _replace_login_sso_hint_with_magic_link(self, errors: AnyDict, email: str) -> None:
        """Replace sentinel login error with a clickable magic-login fallback link."""
        if errors.get("password") != self._LOGIN_SSO_ACCOUNT_HINT_ERROR:
            return

        magic_link_url = URL("auth/request_magic_login", vars={"email": email}, use_appname=False)
        errors["password"] = CAT(
            "Dit e-mailadres is gekoppeld aan SSO. ",
            A("Vraag hier een magic login-link per e-mail aan.", _href=magic_link_url),
        )

    def register(self, model: bool = False) -> AnyDict | str | Form:
        """Show SSO-specific guidance and magic-login fallback on register conflicts."""
        result = super().register(model=model)
        if not isinstance(result, Form):
            return result

        if result.errors.get("email") != SSO_REGISTERED_ACCOUNT_ERROR:
            return result

        entered_email = str(result.vars.get("email") or "").strip()
        magic_link_url = URL("auth/request_magic_login", vars={"email": entered_email}, use_appname=False)
        result.errors["email"] = CAT(
            "Dit e-mailadres is al geregistreerd via SSO. ",
            A("Vraag hier een magic login-link per e-mail aan.", _href=magic_link_url),
        )
        return result

    def request_reset_password(self, model: bool = False) -> AnyDict | str | Form:
        """Show the preferred Entree login route alongside the email fallback."""
        result = super().request_reset_password(model=model)
        if model or not isinstance(result, Form) or result.submitted or "oauth2kennisnet" not in self.auth.plugins:
            return result

        sso_login_url = URL(f"{self.auth.route}/plugin/oauth2kennisnet/login")
        result.param.sidecar.append(
            DIV(
                "Gebruik je Entree? Log dan bij voorkeur in via SSO. ",
                A("Inloggen via Entree", _href=sso_login_url),
            )
        )
        self.log_auth_action(action="sso-reset-option-opened", success=True)
        return result

    def verify_email(self, model: bool = False) -> AnyDict | None:
        """Verify the email token, pass the resolved user to hooks, and auto-login on success."""
        if model:
            return super().verify_email(model=model)

        token = request.query.get("token")

        user = AuthUser.where(self.auth._query_from_token(token)).first()
        verified = self.auth.verify_email(token)

        if verified and user:
            self.auth.store_user_in_session(user.id)

        self._set_flash("email-verified" if verified else "link-expired")
        self._postprocessing("verify_email", user=user, success=verified)

        return None

    def request_magic_login(self, model: bool = False) -> AnyDict | None:
        """Send a one-click login link and redirect back to login."""
        if model:
            return {
                "public": True,
                "hidden": True,
                "fields": [],
                "href": URL(f"{self.auth.route}/request_magic_login"),
                "submit_label": None,
                "additional_buttons": [],
            }

        email = str(request.query.get("email") or "").strip()
        token: str | None = None
        if email:
            token = self.auth.request_magic_login(email, send=True)

        self._set_flash("magic-login-link-sent")
        self._postprocessing(
            "request_magic_login",
            form=None,
            user=None,
            email=email or None,
            success=bool(token),
            details={"token_issued": bool(token)},
        )
        return None

    def magic_login(self, model: bool = False) -> AnyDict | None:
        """Consume a magic-login token and sign the user in."""
        if model:
            return {
                "public": True,
                "hidden": True,
                "fields": [],
                "href": URL(f"{self.auth.route}/magic_login"),
                "submit_label": None,
                "additional_buttons": [],
            }

        user, error = self.auth.consume_magic_login_token(request.query.get("token"))
        if error:
            self.log_auth_action(
                action="magic_login",
                success=False,
                details={"reason": error},
            )
            self._set_flash(error)
            raise redirect(URL("auth", "login", use_appname=False))

        assert user
        self.auth.store_user_in_session(user.id)
        self._set_flash("magic-login-success")
        self._postprocessing("magic_login", user=user)
        return None

    def _postprocessing(
        self,
        action: str,
        form: Form | None = None,
        user: AuthUser | None = None,
        email: str | None = None,
        success: bool | None = None,
        details: AnyDict | None = None,
    ) -> None:
        if action == "logout":
            raise redirect(URL("auth", "login", use_appname=False))

        log_success = success if success is not None else (bool(form.accepted) if form else True)
        self.log_auth_action(
            action=action,
            success=log_success,
            user=(user.as_dict() if user else {}),
            email=email,
            details=details,
        )

        if action == "reset_password" and user and user.sso_id:
            self.log_auth_action(
                action="sso-password-reset",
                success=log_success,
                user=user.as_dict(),
                email=normalize_email_for_lookup(user.email),
            )

        if action in self.auth.on_accept and user:
            self.auth.on_accept[action](form, user)

        if not form or form.accepted:
            next_page = (
                URL("auth", "login", use_appname=False)
                if action in self._LOGIN_REDIRECT_ACTIONS
                else self.auth.session.pop(f"_next_{action}", None) or self._redirect_target_for_authenticated_user()
            )
            raise redirect(next_page)

    def log_auth_action(
        self,
        action: str,
        success: bool,
        user: AnyDict | Row | None = None,
        email: str | None = None,
        details: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        """Record the auth event with the current user context."""
        user = user or {}
        self.applog.log_auth_action(
            action=action,
            user_gid=user.get("gid"),
            email=email or user.get("email"),
            success=success,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            details=details,
        )

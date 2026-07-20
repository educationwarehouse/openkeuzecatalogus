"""Auth form hooks with applog integration."""

import typing as t

from py4web.utils.auth import DefaultAuthForms
from py4web.utils.form import Form
from pydal.objects import Row
from yatl import DIV

from py4web import URL, redirect, request
from shared_code.data_model.tables import AuthUser
from shared_code.services import Applogger

if t.TYPE_CHECKING:
    from common.models.backend.auth_cls import AppAuth


class LoggingAuthForms(DefaultAuthForms):
    """Auth form hooks that write auth activity to the applogger."""

    _LOGIN_REDIRECT_ACTIONS: t.ClassVar[set[str]] = {
        "register",
        "request_reset_password",
        "reset_password",
    }

    def __init__(self, _auth: AppAuth, applog: Applogger) -> None:
        """Initialise the form hooks with an auth instance and logger."""
        super().__init__(_auth)
        self.applog = applog

    def _redirect_target_for_authenticated_user(self) -> str:
        """Send authenticated users to their landing page instead of the login form."""
        if self.auth.auth_context.is_admin():
            return URL("admin", "index", use_appname=False)
        else:
            return URL("index", use_appname=False)

    @t.overload
    def logout(self, model: t.Literal[True]) -> dict[str, t.Any]: ...

    @t.overload
    def logout(self, model: t.Literal[False]) -> str: ...

    def logout(self, model: bool = False) -> dict[str, t.Any] | str:  # ty: ignore[invalid-method-override]
        """Log logout attempts before delegating to the base implementation."""
        user = self.auth.get_user()
        self.log_auth_action(action="logout", success=True, user=user.as_dict() if user else {})
        return super().logout(model=model)

    def login(self, model: bool = False) -> dict[str, t.Any] | str | Form:
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

            top_buttons = self.login_buttons()  # rebuild oauth plugin buttons
            result.structure.insert(0, DIV(top_buttons["combined_div"]))

        return result

    def verify_email(self, model: bool = False) -> dict[str, t.Any] | None:
        """Verify the email token, pass the resolved user to hooks, and auto-login on success."""
        if model:
            return super().verify_email(model=model)

        token = request.query.get("token")
        user = AuthUser.where(self.auth._query_from_token(token)).first()
        verified = self.auth.verify_email(token)

        if verified and user:
            self.auth.store_user_in_session(user.id)

        self._set_flash("email-verified" if verified else "link-expired")
        self._postprocessing("verify_email", user=user)

        return None

    def _postprocessing(self, action: str, form: Form | None = None, user: AuthUser | None = None) -> None:
        if action == "logout":
            # no form to post-process
            return

        success = bool(form.accepted) if form else True
        self.log_auth_action(action=action, success=success, user=(user.as_dict() if user else {}))

        if action in self.auth.on_accept:
            self.auth.on_accept[action](form, user)

        if not form or form.accepted:
            next_page = self.auth.session.get(f"_next_{action}") or (
                URL("auth", "login", use_appname=False) if action in self._LOGIN_REDIRECT_ACTIONS else URL("index")
            )
            raise redirect(next_page)

    def log_auth_action(
        self,
        action: str,
        success: bool,
        user: dict[str, t.Any] | Row | None = None,
        email: str | None = None,
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
        )

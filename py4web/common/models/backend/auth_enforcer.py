"""Auth enforcer helpers for login redirects."""

from py4web.utils.auth import AuthEnforcer


class LoginRedirectAuthEnforcer(AuthEnforcer):
    """Auth enforcer that always redirects unauthenticated users to `/auth/login`."""

    def goto_login(self, message: str = "") -> None:
        """Redirect to the login page with an optional flash message."""
        self.abort_or_redirect("login", message=message)

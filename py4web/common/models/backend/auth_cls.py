"""Authentication wiring and auth-form extensions for the py4web app."""

import typing as t
import uuid

from edwh_auth_rbac.model import IdentityKey
from py4web.utils.auth import Auth, b16e
from py4web.utils.form import FormStyleBootstrap5
from pydal.objects import Row
from typedal.for_py4web import DAL
from typedal.types import Query

from common.fixtures.requires_fixture import Condition, OrElse, RequiresFixture
from common.fixtures.session import PoppableSession
from py4web import HTTP, URL, redirect, request
from shared_code.data_model import AnyDict
from shared_code.data_model.constants import ROLE_SUPPLIER
from shared_code.data_model.tables import AuthUser
from shared_code.data_model.validators.is_existing_sso_account import build_normalized_email_match_query
from shared_code.modules.auth import (
    AuthContext,
    AuthScope,
)
from shared_code.modules.auth.password_reset import (
    RESET_PASSWORD_LINK_MAX_AGE_HOURS,
    is_reset_password_request_active,
    mark_reset_password_expiry,
    reset_password_expires_at,
    validate_reset_password_token,
)
from shared_code.util.email import normalize_email_for_lookup

from ... import settings
from ..entree import setup_entree_plugin
from .auth_enforcer import LoginRedirectAuthEnforcer
from .auth_forms import LoggingAuthForms
from .backend_base import Py4webBackend

ALLOWED_ACTIONS = [
    "login",
    "logout",
    "request_magic_login",
    "request_reset_password",
    "magic_login",
    "reset_password",
    "change_password",
    "profile",
    "register",
    "verify_email",
]

ACCOUNT_BLOCKED = "account-blocked"


class AppAuth(Auth):
    """Auth adapter that emits applog events for selected auth actions."""

    db: DAL
    form_source: LoggingAuthForms
    auth_context: AuthContext
    param: t.Any

    MESSAGES = {
        "verify_email": {
            "subject": "Bevestig je e-mailadres",
            "body": "Hallo {first_name}, klik {link} om je e-mailadres te bevestigen.",
        },
        "reset_password": {
            "subject": "Wachtwoord opnieuw instellen",
            "body": (
                "Hallo {first_name}, klik {link} om je wachtwoord opnieuw in te stellen. "
                f"Deze link is slechts {RESET_PASSWORD_LINK_MAX_AGE_HOURS} uur geldig."
            ),
        },
        "magic_login": {
            "subject": "Magic login-link",
            "body": (
                "Hallo {first_name}, klik {link} om direct in te loggen. "
                f"Deze link is slechts {RESET_PASSWORD_LINK_MAX_AGE_HOURS} uur geldig."
            ),
        },
        "unsubscribe": {
            "subject": "Unsubscribe confirmation",
            "body": "By {first_name}, you have been erased from our system",
        },
        "flash": {
            "User registered": (
                "Registratie succesvol. Er wordt een verificatiemail gestuurd. Controleer ook je spam."
            ),
            "user registered": (
                "Registratie succesvol. Er wordt een verificatiemail gestuurd. Controleer ook je spam."
            ),
            "Registration is pending": "Dit e-mailadres is nog niet gevalideerd.",
            "Invalid Credentials": "Ongeldige inloggegevens.",
            "user-registered": (
                "Registratie succesvol. Er wordt een verificatiemail gestuurd. Controleer ook je spam."
            ),
            "password-reset-link-sent": "Als dit e-mailadres bij ons bekend is, "
            "ontvang je een link om je wachtwoord opnieuw in te stellen.",
            "magic-login-link-sent": "Als dit e-mailadres bij ons bekend is, "
            "ontvang je een link waarmee je kunt inloggen.",
            "password-changed": "Je wachtwoord is gewijzigd.",
            "profile-saved": "Je profiel is opgeslagen.",
            "user-logout": "Je bent uitgelogd.",
            "email-verified": "Je e-mailadres is bevestigd.",
            "link-invalid": "Deze link is ongeldig.",
            "login-required": "Je moet ingelogd zijn.",
            "link-expired": "Deze link is verlopen.",
        },
        "labels": {
            "username": "Gebruikersnaam",
            "email": "E-mailadres",
            "first_name": "Voornaam",
            "last_name": "Achternaam",
            "phone_number": "Telefoonnummer",
            "username_or_email": "Gebruikersnaam of e-mailadres",
            "password": "Wachtwoord",
            "new_password": "Nieuw wachtwoord",
            "old_password": "Huidig wachtwoord",
            "login_password": "Wachtwoord",
            "password_again": "Wachtwoord (nogmaals)",
            "created_on": "Aangemaakt op",
            "created_by": "Aangemaakt door",
            "modified on": "Gewijzigd op",
            "modified by": "Gewijzigd door",
            "two_factor": "Authenticatiecode",
        },
        "buttons": {
            "lost-password": "Wachtwoord vergeten",
            "register": "Registreren",
            "request": "Versturen",
            "sign-in": "Inloggen",
            "sign-up": "Registreren",
            "submit": "Versturen",
        },
        "errors": {
            "registration_is_pending": "Dit e-mailadres is nog niet gevalideerd.",
            "account_is_blocked": "Dit account is geblokkeerd.",
            "account_needs_to_be_approved": "Dit account moet eerst worden goedgekeurd.",
            "invalid_credentials": "Ongeldige inloggegevens.",
            "invalid_token": "Ongeldig token.",
            "password_doesnt_match": "De wachtwoorden komen niet overeen.",
            "invalid_current_password": "Het huidige wachtwoord is onjuist.",
            "new_password_is_the_same_as_previous_password": (
                "Het nieuwe wachtwoord mag niet gelijk zijn aan het vorige wachtwoord."
            ),
            "new_password_was_already_used": "Dit wachtwoord is al eerder gebruikt.",
            "invalid": "Ongeldige invoer.",
            "no_post_payload": "Ontbrekende formuliergegevens.",
            "two_factor": "De verificatiecode klopt niet.",
            "two_factor_max_tries": "Het maximum aantal verificatiepogingen is overschreden.",
        },
    }

    def __init__(self, backend: Py4webBackend, **kwargs: t.Any) -> None:
        """Initialise the auth adapter and install the logging form source."""
        super().__init__(**kwargs)
        self.backend = backend
        self.form_source = LoggingAuthForms(self, applog=backend.applog)
        self.auth_context = backend.auth_context

    def on_success(self, context: AnyDict) -> None:
        """Inject 'auth' into the yatl template."""
        super().on_success(context)
        if (output := context.get("output")) and isinstance(output, dict):
            # note: works better than `template_inject`
            output.setdefault("auth", self)

    @classmethod
    def from_dependencies(cls, session: PoppableSession, db: DAL, backend: Py4webBackend) -> t.Self:
        """Build an auth instance from the injected backend dependencies."""
        auth = cls(session=session, db=db, define_tables=False, backend=backend)
        auth.param.auth_enforcer = LoginRedirectAuthEnforcer(auth)
        auth.use_username = False
        auth.param.registration_requires_confirmation = not settings.AUTO_APPROVE_AND_LOGIN_AFTER_REGISTRATION
        auth.param.registration_requires_approval = False
        auth.param.login_after_registration = settings.AUTO_APPROVE_AND_LOGIN_AFTER_REGISTRATION
        auth.param.allowed_actions = ALLOWED_ACTIONS
        auth.param.login_expiration_time = settings.SESSION_IDLE_SECONDS
        auth.param.password_complexity = {"entropy": 50}
        auth.param.block_previous_password_num = 3
        auth.param.default_login_enabled = True
        auth.param.use_appname_in_redirects = False

        production_entree = (
            settings.ENTREE_CLIENT_ENDPOINT and settings.ENTREE_CLIENT_ID and settings.ENTREE_CLIENT_SECRET
        )

        if settings.ENTREE_FAKE or production_entree:
            setup_entree_plugin(backend.entree_oauth, auth)

        auth.param.formstyle = FormStyleBootstrap5  # will be replaced via EddieFormStyle.bind_auth() later
        auth.fix_actions()
        for custom_action in ("request_magic_login", "magic_login"):
            if custom_action not in auth.param.allowed_actions:
                auth.param.allowed_actions.append(custom_action)
        auth.on_accept["verify_email"] = auth.grant_roles_after_email_verification

        auth.sender = backend.mailer
        return auth

    def is_valid(self) -> bool:
        """Return whether the current auth session is valid."""
        return self.session.is_valid()

    def get_user(self, safe: bool = True) -> AuthUser | None:
        """Return the current user record, optionally restricting readable fields."""
        builder = AuthUser.where(id=self.user_id)
        if safe:
            readable_columns = (col for col in AuthUser if col.readable)
            builder = builder.select(*readable_columns)

        return builder.first()

    def _normalize_auth_email_input(self, email: str) -> str:
        """Normalize email input for auth flows that perform lookups."""
        return normalize_email_for_lookup(email)

    def _sso_user_for_email(self, email: str) -> AuthUser | None:
        """Return the federative account associated with an email address."""
        normalized_email = self._normalize_auth_email_input(email)
        query = (AuthUser.sso_id != None) & build_normalized_email_match_query(AuthUser.email, normalized_email)
        return AuthUser.where(query).first()

    def ensure_not_blocked(self, user_or_query: AuthUser | Query | bool) -> AuthUser | None:
        """Resolve an account when needed and reject it when it is blocked."""
        user = user_or_query if isinstance(user_or_query, AuthUser) else AuthUser.where(user_or_query).first()
        if user and user.action_token == ACCOUNT_BLOCKED:
            raise HTTP(403, self._flash_message_text("account_is_blocked"))

        return user

    def login(self, email: str, password: str) -> tuple[Row, None] | tuple[None, str]:
        """Log successful and failed login attempts."""
        email = self._normalize_auth_email_input(email)
        user, error = super().login(email, password)
        if not user and (sso_user := self._sso_user_for_email(email)):
            user, error = super().login(sso_user.email, password)

        if user:
            self.form_source.log_auth_action("login", success=True, user=user, email=email)
        else:
            self.form_source.log_auth_action("invalid_login_attempt", success=False, email=email)

        return user, error

    def _flash_message_text(self, key: str) -> str:
        return self.MESSAGES.get("flash", {}).get(key) or self.MESSAGES.get("errors", {}).get(key, key)

    def _send_flash(self, key: str, class_name: str = "alert-info") -> None:
        """Show a translated flash message with the requested severity class."""
        self.flash.set(self._flash_message_text(key), class_name)

    def send_flash(self, message: str, status: str = "info") -> None:
        """Show a flash message with a Bootstrap severity suffix."""
        self._send_flash(message or "?", class_name=f"alert-{status}")

    def flash_error(self, key: str) -> None:
        """Show an error flash message."""
        self.send_flash(key, status="danger")

    def flash_warning(self, key: str) -> None:
        """Show a warning flash message."""
        self.send_flash(key, status="warning")

    def flash_success(self, key: str) -> None:
        """Show a success flash message."""
        self.send_flash(key, status="success")

    def flash_info(self, key: str) -> None:
        """Show an informational flash message."""
        self.send_flash(key, status="info")

    def _query_from_token(self, token: str) -> Query:
        """Resolve reset-password tokens while preserving the base fallback."""
        user_id, error = validate_reset_password_token(token)

        if error:
            self.flash_error(error)
            return redirect(URL("auth/request_reset_password", use_appname=False))
        elif user_id:
            return AuthUser.id == user_id
        else:
            return super()._query_from_token(token)

    def request_reset_password(
        self,
        email: str,
        send: bool = True,
        next: str = "",
        route: str | None = None,
    ) -> str | None:
        """Create a reset token for local or federative accounts and persist its expiry."""
        email = self._normalize_auth_email_input(email)
        sso_user = self._sso_user_for_email(email)
        if not sso_user:
            token = super().request_reset_password(email, send=send, next=next, route=route)
        elif sso_user.action_token == ACCOUNT_BLOCKED:
            # Intentional: blocked accounts get no reset token.
            # This differs from ensure_not_blocked() which raises HTTP 403.
            # Here we return None silently so the caller can fall through to
            # the normal "if token: send email" path without sending a reset.
            # US 7875: "Wachtwoord herstel moet via E-mail kunnen, ook bij
            # federatieve accounts" — but blocked accounts are explicitly excluded.
            token = None
        else:
            token = str(uuid.uuid4())
            if next:
                token += "/" + b16e(next)
            sso_user.update_record(action_token=f"reset-password-request:{token}")
            if send:
                self._link = link = URL(
                    route or self.route,
                    "reset_password",
                    vars={"token": token},
                    scheme=True,
                    use_appname=self.param.use_appname_in_redirects,
                )
                email_recipient = sso_user.as_dict()
                email_recipient["email"] = email
                self.send("reset_password", email_recipient, link=link)

            self.backend.applog.log_auth_action(
                action="sso-reset-requested",
                user_gid=sso_user.gid,
                email=email,
                success=True,
            )
        if token:
            mark_reset_password_expiry(token)
        return token

    def get_or_register_user(self, user: AnyDict) -> AnyDict | None:
        """Attach a new federative identity to its existing local account when available."""
        if sso_id := user.get("sso_id"):
            if existing_sso_account := self.ensure_not_blocked(AuthUser.sso_id == sso_id):
                return existing_sso_account.as_dict()

            normalized_email = self._normalize_auth_email_input(str(user.get("email") or ""))
            local_account_query = (AuthUser.email == normalized_email) & (
                (AuthUser.sso_id == None) | (AuthUser.sso_id == "")
            )

            if local_account := self.ensure_not_blocked(local_account_query):
                local_account.update_record(sso_id=sso_id)
                return local_account.as_dict()

            existing_sso_user = self._sso_user_for_email(str(user.get("email") or ""))
            if existing_sso_user:
                raise HTTP(409, "Dit e-mailadres is al gekoppeld aan een SSO-account.")

        return super().get_or_register_user(user)

    def request_magic_login(
        self,
        email: str,
        send: bool = True,
        route: str | None = None,
    ) -> str | None:
        """Create a one-click magic login token and send it via email."""
        normalized_email = self._normalize_auth_email_input(email)
        user_query = build_normalized_email_match_query(AuthUser.email, normalized_email)
        user = AuthUser.where(user_query).select(AuthUser.id, AuthUser.first_name, AuthUser.action_token).first()

        if not user or user.action_token == ACCOUNT_BLOCKED:
            return None

        token = str(uuid.uuid4())
        user.update_record(
            action_token=f"magic-login-request:{token}",
            reset_password_expires_at=reset_password_expires_at(),
        )

        if send:
            link = URL(
                route or self.route,
                "magic_login",
                vars={"token": token},
                scheme=True,
                use_appname=self.param.use_appname_in_redirects,
            )
            self.send(
                "magic_login",
                {
                    "email": normalized_email,
                    "first_name": user.first_name or "gebruiker",
                },
                link=link,
            )

        return token

    def consume_magic_login_token(self, token: str | None) -> tuple[AuthUser | None, str | None]:
        """Resolve a magic login token and consume it when valid."""
        if not token:
            return None, "link-invalid"

        user = (
            AuthUser.where(action_token=f"magic-login-request:{token}")
            .select(
                AuthUser.id,
                AuthUser.gid,
                AuthUser.email,
                AuthUser.reset_password_expires_at,
            )
            .first()
        )

        if not user:
            return None, "link-invalid"
        elif not is_reset_password_request_active(expires_at=user.reset_password_expires_at):
            return None, "link-expired"

        user.update_record(action_token=None, reset_password_expires_at=None)
        return user, None

    def grant_memberships(self, user: AuthUser) -> None:
        """Grant the matching supplier membership for a user email, if any."""
        self.backend.suppliers.grant_memberships(user)
        self.backend.organisations.grant_memberships(user)

    def store_user_in_session(self, user_id: int) -> None:
        """Persist the session and refresh supplier membership on every login path."""
        super().store_user_in_session(user_id)
        if user := AuthUser(user_id):
            self.grant_memberships(user)

        if "_next" not in self.session:
            self.session["_next"] = self._sso_default_redirect_target()

    def _sso_default_redirect_target(self) -> str:
        """Choose the default post-SSO route after the user's roles are available."""
        return (
            URL("admin", "index", use_appname=False)
            if self.auth_context.is_admin() or self.auth_context.has_membership(ROLE_SUPPLIER)
            else URL("index", use_appname=False)
        )

    def grant_roles_after_email_verification(self, _form: None, user: AuthUser) -> None:
        """Grant supplier-backed memberships when a user verifies their email."""
        self.grant_memberships(user)

    def requires(self, condition: Condition, or_else: OrElse = None) -> RequiresFixture:
        """Add a generic `auth.requires()` functionality.

        Requirements can be combined using | (OR) and & (AND).

        Usage:
            >>> @action.uses(auth.requires(True, None))
            >>> @action.uses(auth.requires(lambda: True, None))

            >>> @action("some/<gid>")
            >>> @action.uses(auth.requires(lambda gid: gid != "00000000-0000-0000-0000-000000000000", None))
            # ^ when using a variable name that matches a dynamic route, the value is injected

            >>> @action.uses(auth.requires(lambda ctx: True, None))
            # ^ otherwise, the context is passed

            >>> @action.uses(auth.requires(bool | lambda, "index"))
            >>> @action.uses(auth.requires(bool | lambda, URL("index")))
            >>> @action.uses(auth.requires(bool | lambda, lambda: "index"))
            >>> @action.uses(auth.requires(bool | lambda, lambda ctx: "index"))
            >>> @action.uses(auth.requires(bool | lambda, lambda ctx: redirect("index")))
            >>> @action.uses(auth.requires(bool | lambda, lambda ctx: HTTP(403, "not allowed")))

            >>> @action.uses(auth.requires(False, str | URL | lambda) | auth.requires(True, str | URL | lambda))
            >>> @action.uses(auth.requires(False, str | URL | lambda) & auth.requires(True, str | URL | lambda))
        """
        return RequiresFixture(self.db, self.session, condition, or_else)

    def _to_login(self, _: t.Any = None) -> str:
        # redirect to login
        return URL("auth/login", vars={"next": request.urlparts.path}, use_appname=False)

    def requires_login(self) -> RequiresFixture:
        """@action.uses(auth.user) is broken, use this instead."""
        return self.requires(lambda: bool(self.get_user()), or_else=self._to_login)

    def has_permission(self, gid: str, scope: AuthScope) -> bool:
        """Return whether the current user may apply `scope` to `gid`."""
        return self.auth_context.is_admin() or self.auth_context.has_permission(gid, scope)

    def requires_permission(
        self,
        scope: AuthScope,
        or_else: OrElse = None,
    ) -> RequiresFixture:
        """Require one RBAC scope for the `gid` captured by the current route."""
        return self.requires_login() & self.requires(
            lambda gid: self.has_permission(gid, scope),
            or_else=or_else,
        )

    def requires_membership(
        self,
        group_identifier: IdentityKey | list[IdentityKey],
        or_else: OrElse = None,
    ) -> RequiresFixture:
        """Require the current user to belong to at least one group."""

        def else_show_error(_: AnyDict) -> str:
            return URL(
                "auth/error",
                vars={"type": "no-roles"},
                scheme=True,
                use_appname=False,
            )  # no roles error page

        or_else = or_else or else_show_error

        group_identifiers = group_identifier if isinstance(group_identifier, (list, tuple)) else [group_identifier]
        return self.requires_login() & self.requires(
            lambda: any(self.auth_context.has_membership(str(identifier)) for identifier in group_identifiers),
            or_else=or_else,
        )

    def is_admin(self) -> bool:
        """Return whether the actor has the admin role."""
        return self.auth_context.is_admin()


__all__ = ["ALLOWED_ACTIONS", "AppAuth"]

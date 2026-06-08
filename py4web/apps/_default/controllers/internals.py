import os
from urllib.parse import urlencode

from py4web import URL, action, redirect, request

from .. import settings
from ..models import db

if os.getenv("COVERAGE_PROCESS_START"):  # pragma: no cover

    @action("_flush-runtime-coverage")
    def flush_runtime_coverage() -> str:
        """Persist runtime coverage from the long-running web process."""
        import coverage

        cov = coverage.Coverage.current()
        if cov is None:
            return "no-coverage"

        cov.save()
        return "flushed"


if settings.ENTREE_FAKE:

    @action("auth/entree_mock_authorize")
    def entree_mock_authorize() -> None:
        """Fake Entree authorize endpoint used in test mode."""
        callback_url = URL("auth/plugin/oauth2kennisnet/callback", scheme=True)
        params = {"code": "mock-entree-code"}
        if state := request.query.get("state"):
            params["state"] = state
        redirect(f"{callback_url}?{urlencode(params)}")


if MOCK_EMAIL_DOMAIN := os.environ.get("PYTEST_MOCK_EMAIL_DOMAIN", ""):

    @action("auth/cleanup_mock_users", method=["POST"])
    @action.uses(db)
    def cleanup_mock_users() -> str:
        """Delete mock auth users created by browser tests."""
        domain = (request.query.get("domain", "") or MOCK_EMAIL_DOMAIN).lstrip("@")
        email_like = f"%@{domain}"

        auth_users = db(db.auth_user.email.like(email_like)).select(db.auth_user.gid)
        gids = [row.gid for row in auth_users if row.gid]

        deleted_memberships = db(db.membership.subject.belongs(gids)).delete() if gids else 0
        deleted_auth_users = db(db.auth_user.email.like(email_like)).delete()
        deleted_identities = db(db.identity.object_id.belongs(gids)).delete() if gids else 0
        db.commit()

        return (
            "cleaned "
            f"{deleted_auth_users} auth users, "
            f"{deleted_identities} identities, "
            f"{deleted_memberships} memberships for {email_like}"
            f" ({gids = })"
        )


@action("ping")
@action.uses(db)
def ping() -> str:
    return "pong"

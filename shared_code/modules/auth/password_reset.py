"""Password reset policy helpers."""

import datetime as dt

from shared_code.data_model.tables import AuthUser
from shared_code.services.time.clock import ensure_utc, utcnow

RESET_PASSWORD_LINK_MAX_AGE_HOURS = 72
RESET_PASSWORD_LINK_MAX_AGE = dt.timedelta(hours=RESET_PASSWORD_LINK_MAX_AGE_HOURS)


def validate_reset_password_token(token: str, now: dt.datetime | None = None) -> tuple[AuthUser | None, str | None]:
    """Return the reset user and error state for a password reset token."""
    reset_user = (
        AuthUser.where(action_token=f"reset-password-request:{token}")
        .select(AuthUser.id, AuthUser.reset_password_expires_at)
        .first()
    )
    if not reset_user:
        return None, None
    elif is_reset_password_request_active(expires_at=reset_user.reset_password_expires_at, now=now):
        return reset_user, None
    else:
        return None, "link-expired"


def mark_reset_password_expiry(
    token: str,
    now: dt.datetime | None = None,
    max_age: dt.timedelta | None = None,
) -> bool:
    """Set the expiry timestamp for the reset-password request identified by `token`."""
    expires_at = reset_password_expires_at(
        now=now,
        max_age=max_age,
    )

    return bool(
        AuthUser.where(action_token=f"reset-password-request:{token}").update(reset_password_expires_at=expires_at)
    )


def reset_password_expires_at(
    *,
    now: dt.datetime | None = None,
    max_age: dt.timedelta | None = None,
) -> dt.datetime:
    """Return the expiry timestamp for a password reset link."""
    current_time = now or utcnow()
    delta = max_age or RESET_PASSWORD_LINK_MAX_AGE
    return ensure_utc(current_time + delta)


def is_reset_password_request_active(
    *,
    expires_at: dt.datetime | None,
    now: dt.datetime | None = None,
) -> bool:
    """Return whether a password reset link is still valid."""
    if expires_at is None:
        return False
    current_time = now or utcnow()
    return ensure_utc(expires_at) >= ensure_utc(current_time)

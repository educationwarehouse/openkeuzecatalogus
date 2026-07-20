"""Tests for password reset policy helpers."""

import datetime as dt
import time

from typedal import TypeDAL

from shared_code.data_model.tables import AuthUser
from shared_code.modules.auth.password_reset import (
    mark_reset_password_expiry,
    validate_reset_password_token,
)
from shared_code.modules.auth.password_reset import is_reset_password_request_active
from shared_code.util.time import ensure_utc

FIXED_NOW = dt.datetime.fromtimestamp(0, tz=dt.UTC)


def _seed_reset_password_user(token: str, expires_at: dt.datetime | None) -> AuthUser:
    """Insert a minimal auth user row for reset-token tests."""
    return AuthUser.insert(
        first_name="Reset",
        last_name="User",
        email=f"{token}@example.com",
        password="hashed-password-placeholder",
        action_token=f"reset-password-request:{token}",
        reset_password_expires_at=expires_at,
    )


def test_validate_reset_password_token_accepts_active_token(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """An unexpired token should resolve to the matching auth user."""
    token = "active-token"
    expires_at = FIXED_NOW + dt.timedelta(hours=1)
    expected_row = _seed_reset_password_user(token=token, expires_at=expires_at)
    db_per_file.commit()

    user, error = validate_reset_password_token(token, now=FIXED_NOW)

    assert error is None
    assert user is not None
    assert user.id == expected_row.id
    assert ensure_utc(user.reset_password_expires_at) == expires_at


def test_validate_reset_password_token_rejects_expired_token(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """An expired token should return the link-expired error."""
    token = "expired-token"
    expires_at = FIXED_NOW - dt.timedelta(seconds=1)
    _seed_reset_password_user(token=token, expires_at=expires_at)
    db_per_file.commit()

    user, error = validate_reset_password_token(token, now=FIXED_NOW)

    assert user is None
    assert error == "link-expired"


def test_validate_reset_password_token_rejects_missing_token(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Unknown tokens should return a neutral miss."""
    user, error = validate_reset_password_token("missing-token")

    assert user is None
    assert error is None


def test_mark_reset_password_expiry_writes_expiry(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """Marking a reset token should store the expected expiry timestamp."""
    token = "mark-expiry-token"
    row = _seed_reset_password_user(token=token, expires_at=None)
    db_per_file.commit()

    max_age = dt.timedelta(hours=12)

    mark_reset_password_expiry(token, now=FIXED_NOW, max_age=max_age)
    db_per_file.commit()

    refreshed = AuthUser(row.id)
    assert ensure_utc(refreshed.reset_password_expires_at) == FIXED_NOW + max_age

    assert is_reset_password_request_active(expires_at=refreshed.reset_password_expires_at, now=FIXED_NOW)
    assert not is_reset_password_request_active(expires_at=refreshed.reset_password_expires_at)


def test_validate_reset_password_token_expires_after_real_time_passage(
    migrated_db_per_file: None,
    db_per_file: TypeDAL,
) -> None:
    """A reset token should stop validating after its expiry time passes."""
    token = "short-lived-token"
    start = dt.datetime.now(dt.UTC)
    expires_at = start + dt.timedelta(seconds=1)
    _seed_reset_password_user(token=token, expires_at=expires_at)
    db_per_file.commit()

    user_before, error_before = validate_reset_password_token(token, now=start)
    assert user_before is not None
    assert error_before is None

    time.sleep(2)

    after = dt.datetime.now(dt.UTC)
    user_after, error_after = validate_reset_password_token(token, now=after)
    assert user_after is None
    assert error_after == "link-expired"

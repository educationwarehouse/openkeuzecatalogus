"""Tests for shared auth-user model behavior."""

import typing as t

from edwh_auth_rbac import AuthRbac

from shared_code.data_model import AuthUser


def test_blank_password_update_preserves_existing_password(
    migrated_db_per_file: None,
    auth_user_factory: t.Callable[..., AuthUser],
    seeded_rbac: AuthRbac,
) -> None:
    """An empty password submission must not replace an existing password."""
    assert migrated_db_per_file is None
    assert seeded_rbac is not None

    user = auth_user_factory(prefix="blank-password-update")
    original_password = user.password

    updated_user, errors = AuthUser.validate_and_update(AuthUser.id == user.id, password="")

    assert errors is None
    assert updated_user is not None
    refreshed_user = AuthUser(user.id)
    assert refreshed_user is not None
    assert refreshed_user.password == original_password

    updated_user2, errors2 = AuthUser.validate_and_update(AuthUser.id == user.id, password="very-secure")

    assert errors2 is None
    assert updated_user2.password != original_password
    assert updated_user2.password != "very-secure"  # should be hashed

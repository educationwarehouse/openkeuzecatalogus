"""Validator to prevent local registration for existing SSO-backed emails."""

import typing as t

from pydal.validators import Validator
from typedal import TypedField
from typedal.types import Field, Query

from shared_code.util.email import normalize_email_for_lookup

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


SSO_REGISTERED_ACCOUNT_ERROR = "sso-registered-account"


def escape_sql_like_value(value: str) -> str:
    """Escape literal characters that have special meaning in SQL LIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_normalized_email_match_query(email_field: Field | TypedField[t.Any], normalized_email: str) -> Query:
    """Build a DB query matching plain emails and prefixed SSO emails."""
    sso_email_suffix_pattern = f"%:{escape_sql_like_value(normalized_email)}"
    return (email_field == normalized_email) | email_field.like(sso_email_suffix_pattern, escape="\\")


# noinspection PyPep8Naming
class IS_NOT_EXISTING_SSO_ACCOUNT(Validator):
    """Reject values that already exist as an SSO-authenticated account email."""

    def __init__(self, db: DatabaseContext, error_message: str = SSO_REGISTERED_ACCOUNT_ERROR) -> None:
        """Initialize the validator with a database handle and validation error code."""
        self.db = db
        self.e = error_message

    def __call__(self, value: str, record_id: int | None = None) -> tuple[str, str | None]:
        """Validate that no SSO user exists for this email."""
        normalized_email = normalize_email_for_lookup(value)
        query = (self.db.auth_user.sso_id != None) & build_normalized_email_match_query(
            self.db.auth_user.email,
            normalized_email,
        )

        if self.db(query).count():
            return value, self.e

        return value, None

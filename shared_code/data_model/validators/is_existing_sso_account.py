"""Validator to prevent local registration for existing SSO-backed emails."""

import typing as t

from pydal.validators import Validator as PydalValidator
from typedal import TypedField
from typedal.types import Field, Query
from typedal.types import Validator as TypedalValidator

from shared_code.util.email import normalize_email_for_lookup

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

type Validator = PydalValidator | TypedalValidator

SSO_REGISTERED_ACCOUNT_ERROR = "sso-registered-account"


# noinspection PyPep8Naming
class IS_NORMALIZED_EMAIL(TypedalValidator):
    """Validate an SSO-prefixed email address without changing its stored value."""

    def __init__(self, validator: Validator) -> None:
        """Initialize the normalizing wrapper around an email validator."""
        self.validator = validator

    def __call__(self, value: str, record_id: int | None = None) -> tuple[str, str | None]:
        """Validate the normalized value while retaining the original SSO identity."""
        _, error = self.validator(normalize_email_for_lookup(value), record_id)
        return value, error


def escape_sql_like_value(value: str) -> str:
    """Escape literal characters that have special meaning in SQL LIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_normalized_email_match_query(email_field: Field | TypedField[t.Any], normalized_email: str) -> Query:
    """Build a DB query matching plain emails and prefixed SSO emails."""
    sso_email_suffix_pattern = f"%:{escape_sql_like_value(normalized_email)}"
    return (email_field == normalized_email) | email_field.like(sso_email_suffix_pattern, escape="\\")


# noinspection PyPep8Naming
class IS_NOT_EXISTING_SSO_ACCOUNT(TypedalValidator):
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

        if record_id is not None:
            query &= self.db.auth_user.id != record_id

        if self.db(query).count():
            return value, self.e

        return value, None


# noinspection PyPep8Naming
class IS_EMPTY_ON_UPDATE(TypedalValidator):
    """Treat an empty value as unchanged when a record is being updated."""

    def __init__(self, validators: Validator | t.Iterable[Validator]) -> None:
        """Wrap validators that should only run when an update provides a value."""
        self.validators = t.cast(
            list[Validator], [validators] if not isinstance(validators, t.Iterable) else list(validators)
        )

    def __call__(self, value: t.Any, record_id: int | None = None) -> tuple[t.Any, str | None]:
        """Skip validation for empty update values and otherwise delegate to each validator."""
        if record_id is not None and value in (None, ""):
            return None, None

        for validator in self.validators:
            value, error = validator(value, record_id)
            if error:
                return value, error

        return value, None

    def formatter(self, value: t.Any) -> t.Any:
        """Apply the wrapped formatters, such as the password-value masking formatter."""
        for validator in reversed(self.validators):
            if fmt := getattr(validator, "formatter", None):
                value = fmt(value)
        return value

"""UUID validation helpers."""

import typing as t
import uuid

from typedal.types import Validator


def is_uuid(something: t.Any) -> bool:
    """Return whether the given value can be interpreted as a UUID."""
    if isinstance(something, uuid.UUID):
        return True

    try:
        if isinstance(something, str):
            uuid.UUID(something.strip())
        elif isinstance(something, bytes):
            uuid.UUID(bytes=something)
        else:
            uuid.UUID(str(something))
        return True
    except Exception:
        return False


# noinspection PyPep8Naming
class IS_UUID(Validator):
    """Validator compatible with pydal field `requires`."""

    def __init__(self, error_message: str = "Ongeldige waarde voor UUID: ", **kw: t.Any) -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.e = error_message

    def __call__(
        self,
        value: str,
        record_id: int | None = None,
        **kw: t.Any,
    ) -> tuple[uuid.UUID | None, str | None]:
        """Validate input and return parsed UUID or validation error tuple."""
        try:
            return value if isinstance(value, uuid.UUID) else uuid.UUID(value.strip()), None
        except Exception:
            return None, f"{self.e}{value!r}"


# noinspection PyPep8Naming
class IS_UUID_OR_NULL(Validator):
    """Validator compatible with pydal field `requires` for nullable UUID values."""

    def __init__(self, error_message: str = "Ongeldige waarde voor UUID: ", **kw: t.Any) -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.e = error_message

    def __call__(
        self,
        value: str | None,
        record_id: int | None = None,
        **kw: t.Any,
    ) -> tuple[uuid.UUID | None, str | None]:
        """Validate nullable UUID input and return parsed UUID or validation error tuple."""
        if not value:
            return None, None

        try:
            return uuid.UUID(str(value).strip()), None
        except Exception:
            return None, f"{self.e}{value!r}"

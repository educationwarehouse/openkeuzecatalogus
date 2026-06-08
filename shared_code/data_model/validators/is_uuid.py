"""UUID validation helpers."""

import typing as t
import uuid


def is_uuid(something: str | uuid.UUID) -> bool:
    """Return whether the given value can be interpreted as a UUID."""
    if isinstance(something, uuid.UUID):
        return True
    try:
        uuid.UUID(something.strip())
        return True
    except Exception:
        return False


# noinspection PyPep8Naming
class IS_UUID:
    """Validator compatible with pydal field `requires`."""

    def __init__(self, error_message: str = "Ongeldige waarde voor UUID: ", **kw: t.Any) -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.e = error_message

    def __call__(self, value: str, **kw: t.Any) -> tuple[uuid.UUID | None, str | None]:
        """Validate input and return parsed UUID or validation error tuple."""
        try:
            return uuid.UUID(value.strip()), None
        except Exception:
            return None, f"{self.e}{value!r}"

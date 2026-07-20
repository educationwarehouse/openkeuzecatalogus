"""Exception-related utility helpers."""

import typing as t


class Required(RuntimeError):
    """Sentinel exception for required arguments."""


def throw(exc: BaseException) -> t.Never:
    """Raise the given exception.

    This function provides a functional way to raise exceptions, allowing
    exception raising to be used in expressions where a statement wouldn't work.

    Args:
        exc: The exception to be raised.

    Returns:
        Never returns normally as an exception is always raised.

    Raises:
        BaseException: Always raises the provided exception.

    Examples:
        >>> value = get_value() or throw(ValueError("No value available"))
        >>> result = data.get('key') if data else throw(KeyError("Missing data"))

    """
    raise exc

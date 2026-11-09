"""Numeric field representer helpers."""

import typing as t
from decimal import Decimal, InvalidOperation

from babel.numbers import format_currency


def dutch_currency(value: int | float | Decimal | str | None, *_: t.Any) -> str:
    """Render a numeric value as a Dutch euro amount."""
    if value is None:
        return ""

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return str(value)

    if not amount.is_finite():
        return str(value)

    # note: use `babel` instead of builtin `locale` because
    #  locale.currency puts the minus after the amount for nl_NL.
    return format_currency(amount, "EUR", locale="nl_NL")

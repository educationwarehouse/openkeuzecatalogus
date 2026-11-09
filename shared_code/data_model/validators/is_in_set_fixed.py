"""Validator variants used by the data model."""

import typing as t

from pydal.validators import IS_IN_SET, ValidationError


# noinspection PyPep8Naming
class IS_IN_SET_FIXED(IS_IN_SET):
    """Validate scalar and multiple values while tolerating an empty option set."""

    # todo: do we still need this?
    def validate(self, value: t.Any, record_id: int | None = None) -> t.Any:
        """Validate a scalar or collection against the configured options."""
        valuemap = dict(self.options(zero=False))
        if self.multiple:
            # if below was values = re.compile("[\w\-:]+").findall(str(value))
            if not value:
                values = []
            elif isinstance(value, (tuple, list)):
                values = value
            else:
                values = [value]
            if isinstance(self.multiple, (tuple, list)) and not self.multiple[0] <= len(values) < self.multiple[1]:
                raise ValidationError(self.translator(self.error_message))
        else:
            values = [value]
        strkeys = set(map(str, valuemap))  # <- added set() so it doesn't break when 'values' is unsorted.
        failures = [x for x in values if str(x) not in strkeys]
        if failures and self.theset:
            raise ValidationError(self.translator(self.error_message))
        return values if self.multiple else value


__all__ = ["IS_IN_SET_FIXED"]

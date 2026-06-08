"""Date representer helpers."""

import datetime as dt

import pytz


def dutch_date(
    dt_obj: dt.datetime | dt.date | str | None,
    _row: object = None,
    timezone: dt.tzinfo | str = "Europe/Amsterdam",
    str_format: str = "%d-%m-%Y %H:%M:%S",
) -> str:
    """Render a date/datetime in Dutch format for table representations."""
    if not isinstance(dt_obj, (dt.datetime, dt.date)):
        return str(dt_obj or "")

    # Handle dt.date by formatting as date only
    if isinstance(dt_obj, dt.date) and not isinstance(dt_obj, dt.datetime):
        return dt_obj.strftime("%d-%m-%Y")

    # Assume the naive datetime is in UTC
    utc_value = dt_obj.replace(tzinfo=dt.UTC)

    # Convert to the target timezone
    localized = utc_value.astimezone(pytz.timezone(timezone) if isinstance(timezone, str) else timezone)

    return localized.strftime(str_format)

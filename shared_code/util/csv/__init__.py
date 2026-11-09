"""Small CSV serialization helpers shared by import flows."""

import csv
import io
import typing as t


def utf8_csv_bytes[CsvKey: str](fieldnames: t.Sequence[CsvKey], rows: t.Iterable[t.Mapping[CsvKey, t.Any]]) -> bytes:
    """Return a UTF-8 CSV with BOM so spreadsheet software recognizes its encoding."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode()

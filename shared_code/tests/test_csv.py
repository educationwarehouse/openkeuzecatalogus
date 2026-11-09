"""Tests for shared CSV serialization helpers."""

import csv
import io

from shared_code.util.csv import utf8_csv_bytes


def test_utf8_csv_bytes_adds_bom_headers_and_rows() -> None:
    """Generated CSV files open as UTF-8 and retain the supplied values."""
    content = utf8_csv_bytes(
        ("location_gid", "product_olid"),
        [{"location_gid": "location-1", "product_olid": "OLID, with comma"}],
    )

    assert content.startswith(b"\xef\xbb\xbf")

    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))

    assert reader.fieldnames == ["location_gid", "product_olid"]
    assert list(reader) == [{"location_gid": "location-1", "product_olid": "OLID, with comma"}]

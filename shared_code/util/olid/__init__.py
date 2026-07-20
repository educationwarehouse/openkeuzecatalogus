"""Onze Leermiddelen ID helpers."""

import hashlib
import typing as t
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from is_isbn.is_isbn import is_isbn


def generate(prefix: str, key: str | t.Any) -> str:
    """Create a new `olid://` uri."""
    scheme = "olid"
    query: dict[str, list[str]] | str = {}
    uri = urlparse(str(key))

    if uri.scheme in {"ean", "isbn", "https", "http"}:
        if uri.scheme in {"https", "http"}:
            hier_part = "https"
            path = uri.netloc + uri.path
        else:
            hier_part = uri.scheme
            path = uri.path
        query = parse_qs(uri.query)
    elif is_isbn(uri.path):
        hier_part = "isbn"
        path = "".join(filter(str.isdigit, str(key)))
    else:
        hier_part = "unregistered"
        path = f"{prefix}/{key}"

    if uri.fragment:
        query["fragment"] = [uri.fragment]

    if isinstance(query, dict):
        query = urlencode({k: v[0] if len(v) == 1 else v for k, v in query.items()})

    about_to_be_uri = str(urlunparse((scheme, hier_part, path, uri.params, query, "")))
    fragment = hashlib.shake_256(about_to_be_uri.encode()).hexdigest(2)
    return f"{about_to_be_uri}#{fragment}"


def generate_supplier_olid(gid: str | t.Any) -> str:
    """Create a supplier OLID from a supplier gid using the shared OLID generator."""
    return generate("supplier", gid)

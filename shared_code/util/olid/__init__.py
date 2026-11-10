"""Onze Leermiddelen ID helpers."""

import hashlib
import re
import typing as t
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from uuid import UUID

from is_isbn.is_isbn import is_isbn
from slugify import slugify

OLID_PATTERN = re.compile(r"olid://(?:isbn|ean|https|unregistered)/[A-Za-z0-9._~:/?@!$&()*+,;=%-]+#[0-9a-f]{4}")


def is_valid_olid(value: str) -> bool:
    """Accept bounded OLID URIs without characters that can escape UI expressions."""
    return len(value) <= 255 and OLID_PATTERN.fullmatch(value) is not None


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
        path = f"{prefix}/{slugify(str(key))}"

    if uri.fragment and hier_part != "unregistered":
        query["fragment"] = [uri.fragment]

    if isinstance(query, dict):
        query = urlencode({k: v[0] if len(v) == 1 else v for k, v in query.items()})

    about_to_be_uri = str(urlunparse((scheme, hier_part, path, uri.params, query, "")))
    hash_input = about_to_be_uri
    if hier_part == "unregistered" and str(key) != slugify(str(key)):
        # Keep the readable slug, but retain distinctions lost by slugification.
        try:
            UUID(str(key))
        except ValueError:
            hash_input += "\0" + str(key)
    fragment = hashlib.shake_256(hash_input.encode()).hexdigest(2)
    return f"{about_to_be_uri}#{fragment}"


def generate_supplier_olid(gid: str | t.Any) -> str:
    """Create a supplier OLID from a supplier gid using the shared OLID generator."""
    return generate("supplier", gid)


def olid_to_isbn(olid: str, prefix: str = "olid://isbn/") -> str | None:
    """Extract the ISBN from an ISBN-based OLID, or return `None` otherwise."""
    if not (olid and olid.startswith(prefix)):
        return None

    olid = olid.removeprefix(prefix)
    return olid.split("#")[0]

"""Email address normalization helpers."""

import typing as t

from typedal.fields import TypedField, rname
from typedal.types import Field


def normalize_email_for_lookup(email: str | None) -> str:
    """Normalize stored auth emails before extracting domains."""
    normalized = (email or "").strip().lower()
    if normalized.startswith("kennisnet:"):
        normalized = normalized.removeprefix("kennisnet:")

    return normalized


def canonicalize_email_for_similarity(email: str | None) -> str:
    """Normalize emails for fuzzy duplicate detection on the local-part."""
    normalized = normalize_email_for_lookup(email)
    if "@" not in normalized:
        return normalized

    local_part, domain = normalized.rsplit("@", 1)
    canonical_local_part = "".join(char for char in local_part if char.isalnum())
    return f"{canonical_local_part}@{domain}"


def email_domain_sql_v1(column: str | Field | TypedField[t.Any]) -> str:
    """Return SQL yielding the same domain `canonicalize_email_for_similarity` derives.

    Accepts a field so query code can pass the column itself, or a bare name for DDL where the
    table is already in scope and no model is bound yet.

    `canonicalize_email_for_similarity` only ever rewrites the local part, so two addresses can
    only be similar when this domain is equal. That makes an equality test on this expression a
    safe pre-filter: it can only widen the candidate set, never drop a row Python would match.
    Keep it in step with `normalize_email_for_lookup`; the Python functions stay the authority on
    whether two addresses actually match.

    `^.*@` is greedy, so it strips everything up to the *last* `@` just like `rsplit("@", 1)`,
    which also makes it immune to SSO prefixes such as `kennisnet:` or `oauth2kennisnet:`.
    Addresses without an `@` come back unchanged; they can never equal a real domain match, and
    the Python check discards them.
    """
    # note: used in migration so create a `_v2` if you want to make any changes.

    reference = column if isinstance(column, str) else rname(column)
    return f"regexp_replace(lower(btrim({reference}, E' \\t\\n\\r\\f\\v')), '^.*@', '')"


def extract_email_domain(email: str | None) -> str | None:
    """Return the normalized email domain, if the input looks like an email."""
    normalized = normalize_email_for_lookup(email)
    if "@" not in normalized:
        return None

    _, domain = normalized.rsplit("@", 1)
    return domain.strip().lower()

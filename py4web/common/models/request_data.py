"""Helpers for turning py4web request data into plain Python structures."""

import dataclasses as dc
import re
import typing as t

from ombott import Request
from ombott.request_pkg.errors import JSONParsingError

from common.models import backend
from py4web import HTTP, request
from shared_code.data_model import AnyDict
from shared_code.modules.catalog_filters import ResolvedCatalogFilters

BRACKET_KEY_RE = re.compile(r"([^\[\]]+)|\[(.*?)\]")


def _split_bracket_key(key: str) -> list[str]:
    """Split `user[address][city]` into `['user', 'address', 'city']`."""
    parts: list[str] = []

    for match in BRACKET_KEY_RE.finditer(key):
        part = match.group(1) if match.group(1) is not None else match.group(2).strip()
        parts.append(part)

    return parts or [key]


def _merge_leaf(existing: t.Any, value: t.Any) -> t.Any:
    """Merge repeated leaf values into a list, without mutating either argument."""
    if existing is None:
        return value

    existing_items = existing if isinstance(existing, list) else [existing]
    value_items = value if isinstance(value, list) else [value]
    return [*existing_items, *value_items]


def _child_container(next_part: str) -> AnyDict | list[t.Any]:
    """Choose a dict or list for the next path segment."""
    return [] if next_part == "" or next_part.isdigit() else {}


def _ensure_index(target: list[t.Any], index: int) -> None:
    """Pad a list so `target[index]` can be assigned safely."""
    missing = index + 1 - len(target)
    if missing > 0:
        target.extend([None] * missing)


def _slot_key(target: AnyDict | list[t.Any], part: str) -> str | int:
    """Translate one path segment into a key that addresses a slot in `target`."""
    if isinstance(target, dict):
        return part

    if not part.isdigit():
        raise ValueError(f"Unsupported form key segment: {part!r}")

    return int(part)


def _read_slot(target: AnyDict | list[t.Any], key: str | int) -> t.Any:
    """Read one slot, padding the list first so the index always exists."""
    if isinstance(target, list):
        index = t.cast(int, key)
        _ensure_index(target, index)
        return target[index]

    return target.get(t.cast(str, key))


def _write_slot(target: AnyDict | list[t.Any], key: str | int, value: t.Any) -> None:
    """Write one slot, padding the list first so the index always exists."""
    if isinstance(target, list):
        index = t.cast(int, key)
        _ensure_index(target, index)
        target[index] = value
        return

    target[t.cast(str, key)] = value


def _assign_path(target: AnyDict | list[t.Any], parts: list[str], value: t.Any) -> None:
    """Assign one bracket-notation path into a nested dict/list structure."""
    part, rest = parts[0], parts[1:]

    if isinstance(target, list) and part == "":
        # An empty segment (`tags[]`) appends a new slot instead of addressing an existing one.
        if not rest:
            target.extend(value if isinstance(value, list) else [value])
            return

        child = _child_container(rest[0])
        target.append(child)
        _assign_path(child, rest, value)
        return

    key = _slot_key(target, part)

    if not rest:
        _write_slot(target, key, _merge_leaf(_read_slot(target, key), value))
        return

    child = _read_slot(target, key)
    if not isinstance(child, (dict, list)):
        child = _child_container(rest[0])
        _write_slot(target, key, child)

    _assign_path(child, rest, value)


def parse_form_data_with_bracket_notation(data: AnyDict) -> AnyDict:
    """Parse form data with bracket notation keys into nested dicts and lists.

    Examples:
        {'user[name]': 'Alice'} -> {'user': {'name': 'Alice'}}
        {'tags[]': ['a', 'b']} -> {'tags': ['a', 'b']}
        {'items[0][name]': 'Apple'} -> {'items': [{'name': 'Apple'}]}
        {'items[1][name]': 'Apple'} -> {'items': [None, {'name': 'Apple'}]}

    """
    result: AnyDict = {}

    for key, value in data.items():
        parts = _split_bracket_key(key)
        if len(parts) > 1:
            _assign_path(result, parts, value)
        else:
            result[key] = value

    return result


def get_request_data(source: Request | None = None) -> AnyDict:
    """Return flat request data merged as query < form < JSON."""
    source = source or request
    query_data = source.query or {}
    try:
        form_data = source.forms or {}
        json_data = source.json
    except (JSONParsingError, ValueError) as error:
        raise HTTP(400, "Ongeldige JSON-aanvraag.") from error
    if json_data is None:
        json_data = {}
    elif not isinstance(json_data, dict):
        raise HTTP(400, "De JSON-aanvraag moet een object bevatten.")
    return query_data | form_data | json_data


def parse_form_data(source: Request | None = None) -> AnyDict:
    """Return merged request data with bracket notation expanded into Python values."""
    return parse_form_data_with_bracket_notation(get_request_data(source=source))


CatalogView = t.Literal["list", "grid"]


@dc.dataclass
class CatalogRequest:
    """Normalized request data for public catalog result pages."""

    page: int
    view: CatalogView
    sort: str
    filters: AnyDict

    @classmethod
    def from_request(cls, request: Request) -> t.Self:
        """Build a normalized catalog request from query, JSON, or form data."""
        filters = parse_form_data(source=request)
        page_raw = t.cast(str | int | None, filters.pop("page", None))
        view_raw = str(filters.pop("view", "") or "grid").strip().lower()
        sort = str(filters.pop("sort", "")).strip().lower()

        if view_raw not in t.get_args(CatalogView):
            raise HTTP(400, "Ongeldige 'view'")

        try:
            page = max(1, int(page_raw or 1))
        except ValueError:
            page = 1

        return cls(
            page=page,
            view=t.cast(CatalogView, view_raw),
            sort=sort,
            filters=filters,
        )

    @property
    def page_limit(self) -> int:
        """Return the page size for the current catalog view."""
        return 50 if self.view == "list" else 12

    def method_filters(self) -> ResolvedCatalogFilters:
        """Resolve public method filters from the request parameters."""
        return backend.methods.resolve_public_method_filters(self.filters)

    def product_filters(self) -> ResolvedCatalogFilters:
        """Resolve public product filters from the request parameters."""
        return backend.products.resolve_public_product_filters(self.filters)


__all__ = [
    "CatalogRequest",
    "get_request_data",
    "parse_form_data",
    "parse_form_data_with_bracket_notation",
]

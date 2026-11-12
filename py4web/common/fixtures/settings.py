"""Typed request settings fixtures for search and form handlers."""

import enum
import types
import typing as t

from configuraptor import check_type
from py4web.core import Fixture
from typedal import QueryBuilder, TypedTable
from typedal.types import Field

from common.models.request_data import parse_form_data
from py4web import HTTP, request
from shared_code.data_model.mixins.search import SearchMixin
from shared_code.data_model.tables.base import TableWithGid

T_Table = t.TypeVar("T_Table", bound=TypedTable)


def convert_to_bool(value: t.Any) -> bool:
    """Normalize common HTML and JSON boolean representations."""
    if isinstance(value, str) and value.isnumeric():
        return bool(int(value))
    if isinstance(value, str):
        lowered = value.lower().strip()
        return lowered in ("1", "on") or lowered.startswith(("y", "t"))
    return bool(value)


def normalize_value[T](value: t.Any, expected_type: type[T], list_separator: str = ",") -> T:
    # Special handling for list[str] to filter empty strings
    if expected_type == list[str] and isinstance(value, list):
        return t.cast(T, [v for v in value if v])

    if check_type(value, expected_type):
        # already ok 👍
        return value

    if expected_type is bool and isinstance(value, str):
        return t.cast(T, convert_to_bool(value))
    elif expected_type == list[str] and isinstance(value, str):
        return [_ for _ in value.split(list_separator) if _]  # type: ignore
    elif callable(expected_type):
        return expected_type(value)  # type: ignore
    else:
        #  🤷
        return value


def _convert_union_value(value: t.Any, annotation: t.Any) -> t.Any:
    """Try union members in order and preserve conversion errors as the cause."""
    errors: list[Exception] = []
    for option in t.get_args(annotation):
        try:
            return convert_typed_value(value, option)
        except (TypeError, ValueError) as exc:
            errors.append(exc)
    options = ", ".join(str(option) for option in t.get_args(annotation))
    raise TypeError(f"Cannot convert {value!r} to any of [{options}]") from errors[-1] if errors else None


def convert_typed_value(value: t.Any, annotation: t.Any) -> t.Any:
    """Convert a runtime value using a type annotation."""
    if annotation in (t.Any, object) or annotation is None:
        return value

    origin = t.get_origin(annotation)
    if origin in (t.Union, types.UnionType):
        return _convert_union_value(value, annotation)

    if origin is t.Literal:
        literal_values = t.get_args(annotation)
        if value in literal_values:
            return value
        raise ValueError(f"Value {value!r} not in literal options {literal_values}")

    if isinstance(annotation, type) and isinstance(value, annotation):
        return value
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return annotation(value)
    return normalize_value(value, annotation)


class SettingsFixture[T_Table: TypedTable](Fixture):
    """Expose typed request settings and collect matching table rows."""

    aliases: t.ClassVar[dict[str, str]] = {}
    converters: t.ClassVar[dict[str, t.Callable[[t.Any], t.Any]]] = {}
    list_separator: t.ClassVar[str] = ","

    limit: int = 0
    page: int = 1
    paginate: bool = False
    order: str | Field | None = None
    cache_ttl: int | None = None
    gids: list[str] | None = None

    def __init__(self) -> None:
        """Bind this fixture instance to its declared table type."""
        super().__init__()
        self._table = self._resolve_table()

    def _resolve_table(self) -> type[T_Table]:
        for cls in self.__class__.__mro__:
            for base in getattr(cls, "__orig_bases__", ()):
                if t.get_origin(base) is SettingsFixture:
                    table = t.get_args(base)[0]
                    if isinstance(table, type) and issubclass(table, TypedTable):
                        return table
        raise TypeError("SettingsFixture subclasses must bind a TypedTable")

    @classmethod
    def setting_annotations(cls) -> dict[str, t.Any]:
        """Return declared request settings, including inherited defaults."""
        return {
            key: annotation
            for key, annotation in t.get_type_hints(cls).items()
            if not key.startswith("_") and t.get_origin(annotation) is not t.ClassVar
        }

    def on_request(self, context: dict[str, t.Any]) -> None:
        """Parse and normalize declared settings for the current request."""
        self._context = context["request-specific-settings"] = {}
        annotations = self.setting_annotations()
        for key, value in parse_form_data(request).items():
            setting_key = self.aliases.get(key, key)
            annotation = annotations.get(setting_key)
            if annotation is None:
                continue
            if value == "":
                continue
            try:
                converted = convert_typed_value(value, annotation)
                if converter := self.converters.get(setting_key):
                    converted = converter(converted)
            except (TypeError, ValueError) as exc:
                raise HTTP(400, f"Ongeldige waarde voor '{key}'") from exc
            self._context[setting_key] = converted

    def __getattribute__(self, key: str) -> t.Any:
        """Read a request-scoped value before falling back to the class default."""
        context = super().__getattribute__("__dict__").get("_context", {})
        if key.startswith("_") or key not in context:
            return super().__getattribute__(key)
        return context[key]

    def __setattr__(self, key: str, value: t.Any) -> None:
        """Store public assignments in the active request context."""
        if hasattr(self, "_context") and not key.startswith("_"):
            self._context[key] = value
        else:
            super().__setattr__(key, value)

    def _get_values(self) -> dict[str, t.Any]:
        return {key: self._context.get(key, getattr(self, key)) for key in self.setting_annotations()}

    def collect(self, **updated_settings: t.Any) -> t.Any:
        """Collect rows through the bound table's whitelabel-style search API."""
        settings = self._get_values() | updated_settings
        page = settings.pop("page")
        limit = settings.pop("limit")
        paginate = settings.pop("paginate")
        cache_ttl = settings.pop("cache_ttl")
        gids = settings.pop("gids")

        table = self._table
        assert issubclass(table, TableWithGid), "The bound search table must expose a GID for filtering"
        assert issubclass(table, SearchMixin), "The bound search table must implement the whitelabel search API"

        builder = QueryBuilder(table)
        if gids:
            builder = builder.where(table.gid.belongs(gids))
        if cache_ttl:
            builder = builder.cache(ttl=cache_ttl)

        from common.models import backend

        backend.applog.try_fire(
            {
                "kind": "event",
                "action": f"search-{table.__name__}",
                "details": settings,
            }
        )
        builder = table.search(**settings, builder=builder)
        return builder.paginate(page=page, limit=limit) if limit or paginate else builder.paginate(page=1, limit=0)


__all__ = ["SettingsFixture", "convert_to_bool", "convert_typed_value"]

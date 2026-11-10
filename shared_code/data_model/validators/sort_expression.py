"""Validation helpers for persisted catalogue sort expressions."""

import typing as t

from pydal.objects import Field
from typedal import TypedTable
from typedal.types import Expression, OrderBy

from shared_code.data_model.tables.method import Method
from shared_code.data_model.tables.product import Product

type CatalogSortTable = type[Product] | type[Method]


def stringify_sort_expression(order: OrderBy | t.Iterable[OrderBy]) -> str:
    """Render catalogue fields as comma-separated names with ~ for descending.

    Handles the parser's tuples and pyDAL's field | field sort expressions.
    Rejects computed expressions that the catalogue parser cannot restore.
    """
    if isinstance(order, str):
        return order
    elif isinstance(order, Field):
        return order.name
    elif isinstance(order, Expression):
        if order.op == order._dialect.invert and isinstance(order.first, Field):
            return f"~{order.first.name}"
        elif order.op == order._dialect.comma:
            return ", ".join((stringify_sort_expression(order.first), stringify_sort_expression(order.second)))
        else:
            raise ValueError("Catalogue sorts only support fields and descending fields")
    elif isinstance(order, t.Iterable):
        return ", ".join(stringify_sort_expression(part) for part in order)
    else:  # pragma: no cover
        raise TypeError(f"Unexpected type={type(order)} for {order=}")


def sort_expression_table_name(order: OrderBy | t.Iterable[OrderBy] | None) -> str | None:
    """Find a sort's source table without retaining a model or database handle."""
    if order is None or isinstance(order, str):
        return None
    elif isinstance(order, Field):
        return order.tablename
    elif isinstance(order, Expression):
        return sort_expression_table_name((order.first, order.second))
    elif isinstance(order, t.Iterable):
        names = {name for part in order if (name := sort_expression_table_name(part)) is not None}
        if len(names) > 1:
            raise ValueError("Catalogue sorts must use fields from a single table")
        else:
            return next(iter(names), None)
    else:
        raise TypeError(f"Unsupported catalogue sort order: {type(order).__name__}")


def restore_sort_expression(table: type[TypedTable], order_expression: str) -> t.Any:
    """Restore cached field names against their currently bound catalogue table."""
    order, issues = parse_sort_expression(table, order_expression)
    if issues:
        raise ValueError(f"Invalid cached catalogue sort expression: {issues}")
    else:
        return order


def parse_sort_expression(
    table: type[TypedTable],
    order_expression: str,
) -> tuple[t.Any, dict[str, list[str]]]:
    """Parse a persisted order expression into a typed orderby value."""
    issues: dict[str, list[str]] = {}
    normalized = order_expression.strip()
    if not normalized:
        issues["other"] = ["no expression passed"]
        return None, issues

    if normalized == "random":
        return "random", issues

    parsed_fields: list[t.Any] = []
    for raw_part in normalized.split(","):
        part = raw_part.strip()
        if not part:
            continue

        descending = part.startswith("~")
        field_name = part[1:] if descending else part
        if field_name not in table.fields:
            issues["fields"] = [field_name]
            return None, issues

        field = table[field_name]
        parsed_fields.append(~field if descending else field)

    if not parsed_fields:
        issues["other"] = ["no sortable fields parsed"]
        return None, issues

    if len(parsed_fields) == 1:
        return parsed_fields[0], issues
    else:
        return tuple(parsed_fields), issues


# noinspection PyPep8Naming
class IS_SORT_EXPRESSION:
    """Validate a DynamicSort order expression against known catalogue tables."""

    def __init__(self, error_message: str = "Ongeldige order expressie") -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.error_message = error_message

    @staticmethod
    def _tables_for_record(record_id: int | None) -> tuple[CatalogSortTable, ...]:
        """Resolve the catalogue tables a persisted sort must support."""
        from shared_code.data_model.tables.dynamic_sort import DynamicSort

        applies_to = None
        if record_id is not None:
            row = DynamicSort(record_id)
            applies_to = row.applies_to if row and row.applies_to else None

        if applies_to == "product":
            return (Product,)
        elif applies_to == "method":
            return (Method,)
        else:
            return (Product, Method)

    def __call__(self, value: str, record_id: int | None = None) -> tuple[str | None, str | None]:
        """Validate a sort expression and return the cleaned value or an error."""
        candidate = value.strip()
        if not candidate:
            return None, self.error_message

        tables = self._tables_for_record(record_id)

        parsed_results = [parse_sort_expression(table, candidate) for table in tables]
        if all(parsed_order is not None for parsed_order, _ in parsed_results):
            return candidate, None

        if record_id is None and any(parsed_order is not None for parsed_order, _ in parsed_results):
            return candidate, None

        field_issues = sorted({field for _, issues in parsed_results for field in issues.get("fields", [])})
        if field_issues:
            wrong_fields = ", ".join(field_issues)
            return None, f"{self.error_message}: onbekend veld {wrong_fields}"

        other_issues = [issue for _, issues in parsed_results for issue in issues.get("other", [])]
        if other_issues:
            return None, f"{self.error_message}: {other_issues[0]}"

        return None, self.error_message
